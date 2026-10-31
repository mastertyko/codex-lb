from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

import app.modules.proxy.service as proxy_module
from app.db.models import Account, AccountStatus
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.usage.repository import UsageRepository
from tests.integration.test_proxy_websocket_responses import (
    _completed_first_turn_upstream_batch,
    _receive_until_terminal,
    _SequencedUpstreamWebSocket,
    _websocket_settings,
)
from tests.integration.test_websocket_paused_account import _assert_no_reserved_usage
from tests.integration.test_websocket_socket_reuse import (
    _DELTA,
    _FIRST,
    _PARENT,
    _complete,
    _create,
    _RetainedSocketFixture,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(20)]


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
def test_credit_gate_on_open_socket_preserves_context_and_reservations(app_instance, monkeypatch, path):
    upstream = _SequencedUpstreamWebSocket(
        [],
        deferred_message_batches=[
            _completed_first_turn_upstream_batch(_PARENT),
            _completed_first_turn_upstream_batch("resp_quota_resumed"),
        ],
    )
    fixture = _RetainedSocketFixture(monkeypatch, [upstream], limited=True)
    settings = _websocket_settings()
    settings.routing_strategy = "quota_first_balanced"

    class Cache:
        async def get(self):
            return settings

    monkeypatch.setattr(proxy_module, "get_settings_cache", Cache)

    async def set_usage(*, other_exhausted):
        async with SessionLocal() as session:
            if not other_exhausted:
                session.add(
                    Account(
                        id="subscription_peer",
                        chatgpt_account_id="subscription_peer",
                        email="peer@example.com",
                        plan_type="plus",
                        access_token_encrypted=b"access",
                        refresh_token_encrypted=b"refresh",
                        id_token_encrypted=b"id",
                        last_refresh=proxy_module.utcnow(),
                        status=AccountStatus.ACTIVE,
                    )
                )
                await session.commit()
            repo = UsageRepository(session)
            for account_id, used in [
                (fixture.account.id, 100.0),
                ("subscription_peer", 100.0 if other_exhausted else 10.0),
            ]:
                await repo.add_entry(
                    account_id,
                    10.0,
                    window="primary",
                    reset_at=int(time.time()) + 3600,
                    window_minutes=300,
                )
                await repo.add_entry(
                    account_id,
                    used,
                    window="secondary",
                    reset_at=int(time.time()) + 3600,
                    window_minutes=10080,
                    credits_has=account_id == fixture.account.id,
                    credits_balance=5.0 if account_id == fixture.account.id else 0.0,
                )
        service = get_proxy_service_for_app(app_instance)
        service._load_balancer._selection_inputs_cache.invalidate()

    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        with client.websocket_connect(path, headers=fixture.headers()) as websocket:
            _complete(websocket, _create([_FIRST]), _PARENT)
            client.portal.call(lambda: set_usage(other_exhausted=False))
            websocket.send_json(_create([_DELTA], parent=_PARENT))
            events, disconnect = _receive_until_terminal(websocket)
            assert disconnect is None
            assert events[-1]["response"]["error"]["code"] == "quota_first_owner_unavailable"
            assert len(upstream.sent_text) == 1
            assert not upstream.closed
            client.portal.call(_assert_no_reserved_usage)
            client.portal.call(lambda: set_usage(other_exhausted=True))
            _complete(websocket, _create([_DELTA], parent=_PARENT), "resp_quota_resumed")
            sent = json.loads(upstream.sent_text[-1])
            assert sent["input"] == [_DELTA]
            assert sent["previous_response_id"] == _PARENT
            assert len(fixture.connects) == 1
