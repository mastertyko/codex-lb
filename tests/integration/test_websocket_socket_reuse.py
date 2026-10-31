from __future__ import annotations

import asyncio
import json
import threading
from collections import deque

import pytest
from fastapi.testclient import TestClient

import app.modules.proxy.api as proxy_api_module
import app.modules.proxy.service as proxy_module
from app.db.models import Account, AccountStatus, ApiKeyUsageReservation
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy._load_balancer.types import AccountLease
from app.modules.proxy.account_cache import clear_account_routing_unavailable
from tests.integration.test_proxy_websocket_responses import (
    _assert_ws_single_response_lifecycle_completed,
    _completed_first_turn_upstream_batch,
    _receive_until_terminal,
    _SequencedUpstreamWebSocket,
    _websocket_response_batch,
    _websocket_settings,
    _ws_event,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(20)]

_PATH = "/backend-api/codex/responses"
_FIRST = {"role": "user", "content": [{"type": "input_text", "text": "Remember amber-moon-728."}]}
_DELTA = {"role": "user", "content": [{"type": "input_text", "text": "Repeat the code."}]}
_PARENT = "resp_retained_first"


def _create(items, *, parent=None):
    payload = {"type": "response.create", "model": "gpt-5.4", "input": items, "stream": True}
    if parent is not None:
        payload["previous_response_id"] = parent
    return payload


class _RetainedSocketFixture:
    """Keep the API and database real while replacing the external transport."""

    def __init__(self, monkeypatch, upstreams, *, limited=False):
        self.upstreams = deque(upstreams)
        self.connects = []
        self.released_leases = []
        self.keys = {}
        self.account = None
        self.limited = limited
        fixture = self
        original_release = proxy_module.LoadBalancer.release_account_lease

        class SettingsCache:
            async def get(self):
                return _websocket_settings()

        async def allow_firewall(_websocket):
            return None

        async def authenticate(authorization, *, request=None):
            return fixture.keys[authorization]

        async def connect(service, headers, *, request_state, **kwargs):
            assert fixture.account is not None
            lease_id = f"retained-test-{len(fixture.connects)}"
            request_state.websocket_stream_lease = AccountLease(
                lease_id=lease_id,
                account_id=fixture.account.id,
                kind="stream",
                acquired_at=0.0,
                api_key_id=request_state.api_key.id,
            )
            fixture.connects.append(lease_id)
            return fixture.account, fixture.upstreams.popleft()

        async def release(load_balancer, lease):
            if lease is not None and lease.lease_id.startswith("retained-test-"):
                fixture.released_leases.append(lease.lease_id)
                return
            await original_release(load_balancer, lease)

        async def write_request_log(service, **kwargs):
            return None

        monkeypatch.setattr(proxy_api_module, "_websocket_firewall_denial_response", allow_firewall)
        monkeypatch.setattr(proxy_api_module, "validate_proxy_api_key_authorization", authenticate)
        monkeypatch.setattr(proxy_module, "get_settings_cache", lambda: SettingsCache())
        monkeypatch.setattr(proxy_module.ProxyService, "_connect_proxy_websocket", connect)
        monkeypatch.setattr(proxy_module.ProxyService, "_write_request_log", write_request_log)
        monkeypatch.setattr(proxy_module.LoadBalancer, "release_account_lease", release)

    async def prepare(self):
        async with SessionLocal() as session:
            account = Account(
                id="retained_socket_owner",
                chatgpt_account_id="retained_socket_owner",
                email="retained-socket@example.com",
                plan_type="plus",
                access_token_encrypted=b"access",
                refresh_token_encrypted=b"refresh",
                id_token_encrypted=b"id",
                last_refresh=proxy_module.utcnow(),
                status=AccountStatus.ACTIVE,
            )
            session.add(account)
            await session.commit()
            await session.refresh(account)
            session.expunge(account)
            self.account = account
            clear_account_routing_unavailable(account.id)
        async with SessionLocal() as session:
            service = ApiKeysService(ApiKeysRepository(session))
            for name in ("first", "second"):
                key = await service.create_key(
                    ApiKeyCreateData(
                        name=f"retained-{name}",
                        allowed_models=None,
                        limits=(
                            [LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1_000_000)]
                            if self.limited
                            else []
                        ),
                    )
                )
                self.keys[f"Bearer {name}"] = await service.get_key_by_id(key.id)

    def headers(self, *, key="first", session="retained-session", conversation="retained-conversation"):
        return {"Authorization": f"Bearer {key}", "session_id": session, "thread-id": conversation}


async def _wait_parked(service, count=1):
    async with asyncio.timeout(3):
        while len(service._websocket_retained.entries) != count:
            await asyncio.sleep(0.005)


def _complete(websocket, payload, expected):
    websocket.send_json(payload)
    events, disconnect = _receive_until_terminal(websocket)
    assert _assert_ws_single_response_lifecycle_completed(events, disconnect) == expected


def test_completed_socket_reconnect_sends_only_delta(app_instance, monkeypatch):
    upstream = _SequencedUpstreamWebSocket(
        [],
        deferred_message_batches=[
            _completed_first_turn_upstream_batch(_PARENT),
            _completed_first_turn_upstream_batch("resp_retained_next"),
        ],
    )
    fixture = _RetainedSocketFixture(monkeypatch, [upstream])
    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        service = get_proxy_service_for_app(app_instance)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            _complete(websocket, _create([_FIRST]), _PARENT)
            websocket.close()
            client.portal.call(_wait_parked, service)
        assert not upstream.closed
        assert fixture.released_leases == []
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            _complete(websocket, _create([_DELTA], parent=_PARENT), "resp_retained_next")
            assert fixture.connects == ["retained-test-0"]
            assert len(upstream.sent_text) == 2
            sent = json.loads(upstream.sent_text[1])
            assert sent["input"] == [_DELTA]
            assert sent["previous_response_id"] == _PARENT
            assert "amber-moon-728" not in upstream.sent_text[1]
            websocket.close()
            client.portal.call(_wait_parked, service)
    assert upstream.closed
    assert fixture.released_leases == ["retained-test-0"]


def test_openai_compatible_route_does_not_retain_codex_socket(app_instance, monkeypatch):
    upstream = _SequencedUpstreamWebSocket([], deferred_message_batches=[_completed_first_turn_upstream_batch(_PARENT)])
    fixture = _RetainedSocketFixture(monkeypatch, [upstream])
    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        service = get_proxy_service_for_app(app_instance)
        with client.websocket_connect("/v1/responses", headers=fixture.headers()) as websocket:
            _complete(websocket, _create([_FIRST]), _PARENT)
            websocket.close()
            assert upstream.closed_event.wait(3)
            client.portal.call(_wait_parked, service, 0)
    assert fixture.released_leases == ["retained-test-0"]


@pytest.mark.parametrize("mismatch", ["key", "session", "conversation", "parent"])
def test_retained_socket_cannot_cross_owner_scope(app_instance, monkeypatch, mismatch):
    first = _SequencedUpstreamWebSocket([], deferred_message_batches=[_completed_first_turn_upstream_batch(_PARENT)])
    replacement = _SequencedUpstreamWebSocket(
        [], deferred_message_batches=[_completed_first_turn_upstream_batch("resp_retained_other")]
    )
    fixture = _RetainedSocketFixture(monkeypatch, [first, replacement])
    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        service = get_proxy_service_for_app(app_instance)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            _complete(websocket, _create([_FIRST]), _PARENT)
            websocket.close()
            client.portal.call(_wait_parked, service)
        options = {mismatch: "second"} if mismatch != "parent" else {}
        parent = "resp_unrelated_parent" if mismatch == "parent" else _PARENT
        with client.websocket_connect(_PATH, headers=fixture.headers(**options)) as websocket:
            websocket.send_json(_create([_DELTA], parent=parent))
            events, disconnect = _receive_until_terminal(websocket)
            assert events or disconnect is not None
        assert len(first.sent_text) == 1
        assert len(fixture.connects) <= 2
    assert first.closed
    assert fixture.released_leases.count("retained-test-0") == 1


@pytest.mark.parametrize("outcome", ["unfinished", "failed"])
def test_noncompleted_socket_is_closed_instead_of_retained(app_instance, monkeypatch, outcome):
    batch = _websocket_response_batch(_PARENT, completed=False)
    if outcome == "failed":
        batch.append(
            _ws_event(
                {
                    "type": "response.failed",
                    "response": {
                        "id": _PARENT,
                        "status": "failed",
                        "error": {"code": "invalid_request_error", "message": "Request rejected."},
                    },
                }
            )
        )
    upstream = _SequencedUpstreamWebSocket([], deferred_message_batches=[batch])
    fixture = _RetainedSocketFixture(monkeypatch, [upstream])
    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        service = get_proxy_service_for_app(app_instance)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            websocket.send_json(_create([_FIRST]))
            if outcome == "unfinished":
                assert websocket.receive_json()["type"] == "response.created"
            else:
                events, disconnect = _receive_until_terminal(websocket)
                assert disconnect is None
                assert events[-1]["type"] == "response.failed"
            websocket.close()
            assert upstream.closed_event.wait(3)
            client.portal.call(_wait_parked, service, 0)
    assert fixture.released_leases == ["retained-test-0"]


def test_revoked_api_key_cannot_reclaim_completed_socket(app_instance, monkeypatch):
    upstream = _SequencedUpstreamWebSocket([], deferred_message_batches=[_completed_first_turn_upstream_batch(_PARENT)])
    fixture = _RetainedSocketFixture(monkeypatch, [upstream])

    async def revoke():
        async with SessionLocal() as session:
            await ApiKeysRepository(session).update(fixture.keys["Bearer first"].id, is_active=False)

    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        service = get_proxy_service_for_app(app_instance)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            _complete(websocket, _create([_FIRST]), _PARENT)
            websocket.close()
            client.portal.call(_wait_parked, service)
        client.portal.call(revoke)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            websocket.send_json(_create([_DELTA], parent=_PARENT))
            events, disconnect = _receive_until_terminal(websocket)
            assert disconnect is None
            assert events[-1]["type"] == "error"
            assert events[-1]["status"] == 401
        assert len(upstream.sent_text) == 1
        assert fixture.connects == ["retained-test-0"]
    assert upstream.closed
    assert fixture.released_leases == ["retained-test-0"]


def test_changed_model_policy_cannot_reclaim_completed_socket(app_instance, monkeypatch):
    upstream = _SequencedUpstreamWebSocket([], deferred_message_batches=[_completed_first_turn_upstream_batch(_PARENT)])
    fixture = _RetainedSocketFixture(monkeypatch, [upstream])

    async def restrict_model():
        async with SessionLocal() as session:
            await ApiKeysRepository(session).update(
                fixture.keys["Bearer first"].id, allowed_models=json.dumps(["gpt-6.1-sol"])
            )

    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        service = get_proxy_service_for_app(app_instance)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            _complete(websocket, _create([_FIRST]), _PARENT)
            websocket.close()
            client.portal.call(_wait_parked, service)
        client.portal.call(restrict_model)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            websocket.send_json(_create([_DELTA], parent=_PARENT))
            events, disconnect = _receive_until_terminal(websocket)
            assert disconnect is None
            assert events[-1]["type"] == "error"
            assert events[-1]["status"] == 403
        assert len(upstream.sent_text) == 1
        assert fixture.connects == ["retained-test-0"]
    assert upstream.closed
    assert fixture.released_leases == ["retained-test-0"]


def test_lost_upstream_during_grace_does_not_replay_incomplete_context(app_instance, monkeypatch):
    class LostUpstream(_SequencedUpstreamWebSocket):
        async def send_text(self, text):
            if self.closed:
                raise RuntimeError("Upstream disappeared during reconnect grace.")
            await super().send_text(text)

    upstream = LostUpstream([], deferred_message_batches=[_completed_first_turn_upstream_batch(_PARENT)])
    fixture = _RetainedSocketFixture(monkeypatch, [upstream])
    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        service = get_proxy_service_for_app(app_instance)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            _complete(websocket, _create([_FIRST]), _PARENT)
            websocket.close()
            client.portal.call(_wait_parked, service)
        client.portal.call(upstream.close)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            websocket.send_json(_create([_DELTA], parent=_PARENT))
            events, disconnect = _receive_until_terminal(websocket)
            assert disconnect is not None or any(event["type"] in {"error", "response.failed"} for event in events)
        assert len(upstream.sent_text) == 1
        assert fixture.connects == ["retained-test-0"]
    assert fixture.released_leases == ["retained-test-0"]


@pytest.mark.parametrize("failure", ["timeout", "cancelled"])
def test_revalidation_failure_releases_prepared_reservation(app_instance, monkeypatch, failure):
    upstream = _SequencedUpstreamWebSocket([], deferred_message_batches=[_completed_first_turn_upstream_batch(_PARENT)])
    fixture = _RetainedSocketFixture(monkeypatch, [upstream], limited=True)
    entered_revalidation = threading.Event()
    reservation_ids = []

    async def reject_revalidation(service, account, *, request_state, api_key):
        assert request_state.api_key_reservation is not None
        reservation_ids.append(request_state.api_key_reservation.reservation_id)
        entered_revalidation.set()
        if failure == "cancelled":
            raise asyncio.CancelledError()
        raise proxy_module.ProxyResponseError(
            502, proxy_module.openai_error("upstream_request_timeout", "Revalidation exceeded its budget.")
        )

    async def wait_reservation_released():
        async with asyncio.timeout(3):
            while True:
                async with SessionLocal() as session:
                    reservation = await session.get(ApiKeyUsageReservation, reservation_ids[0])
                    assert reservation is not None
                    if reservation.status == "released":
                        return
                await asyncio.sleep(0.005)

    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        service = get_proxy_service_for_app(app_instance)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            _complete(websocket, _create([_FIRST]), _PARENT)
            websocket.close()
            client.portal.call(_wait_parked, service)
        monkeypatch.setattr(proxy_module.ProxyService, "_revalidate_open_websocket_account", reject_revalidation)
        with client.websocket_connect(_PATH, headers=fixture.headers()) as websocket:
            websocket.send_json(_create([_DELTA], parent=_PARENT))
            assert entered_revalidation.wait(3)
        assert len(reservation_ids) == 1
        client.portal.call(wait_reservation_released)
        client.portal.call(_wait_parked, service, 0)
        assert len(upstream.sent_text) == 1
        assert upstream.closed
        assert fixture.released_leases == ["retained-test-0"]
