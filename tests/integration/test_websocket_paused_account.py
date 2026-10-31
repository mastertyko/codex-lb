from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.modules.proxy.service as proxy_module
from app.db.models import AccountStatus, ApiKeyUsageReservation
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.accounts.service import AccountsService
from tests.integration.test_proxy_websocket_responses import (
    _completed_first_turn_upstream_batch,
    _receive_until_terminal,
    _SequencedUpstreamWebSocket,
    _websocket_response_batch,
)
from tests.integration.test_websocket_socket_reuse import (
    _DELTA,
    _FIRST,
    _PARENT,
    _complete,
    _create,
    _RetainedSocketFixture,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(20)]


async def _set_paused(fixture, paused):
    async with SessionLocal() as session:
        service = AccountsService(AccountsRepository(session))
        if paused:
            assert await service.pause_account(fixture.account.id)
        else:
            assert await service.reactivate_account(fixture.account.id)


async def _assert_no_reserved_usage():
    async with SessionLocal() as session:
        rows = (await session.scalars(select(ApiKeyUsageReservation))).all()
        assert rows
        assert all(row.status != "reserved" for row in rows)


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
@pytest.mark.parametrize("parent", [None, _PARENT])
@pytest.mark.parametrize("pause_during_admission", [False, True])
def test_open_socket_blocks_paused_account_and_resumes_same_context(
    app_instance, monkeypatch, path, parent, pause_during_admission
):
    upstream = _SequencedUpstreamWebSocket(
        [],
        deferred_message_batches=[
            _completed_first_turn_upstream_batch(_PARENT),
            _completed_first_turn_upstream_batch("resp_after_reactivation"),
        ],
    )
    fixture = _RetainedSocketFixture(monkeypatch, [upstream], limited=True)
    logs = []

    async def record(service, **kwargs):
        logs.append(kwargs)

    monkeypatch.setattr(proxy_module.ProxyService, "_write_request_log", record)
    original_acquire = proxy_module.ProxyService._acquire_account_response_create_lease_or_overload
    pause_next = False

    async def acquire(service, **kwargs):
        nonlocal pause_next
        lease = await original_acquire(service, **kwargs)
        if pause_next:
            pause_next = False
            await _set_paused(fixture, True)
        return lease

    monkeypatch.setattr(proxy_module.ProxyService, "_acquire_account_response_create_lease_or_overload", acquire)
    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        try:
            with client.websocket_connect(path, headers=fixture.headers()) as websocket:
                _complete(websocket, _create([_FIRST]), _PARENT)
                if pause_during_admission:
                    pause_next = True
                else:
                    client.portal.call(_set_paused, fixture, True)
                # The socket intentionally retains an older ACTIVE ORM snapshot.
                assert fixture.account.status == AccountStatus.ACTIVE
                websocket.send_json(_create([_DELTA], parent=parent))
                events, disconnect = _receive_until_terminal(websocket)
                assert disconnect is None
                assert len(events) == 1
                assert events[0]["type"] == "response.failed"
                expected = "previous_response_owner_unavailable" if parent else "preferred_account_unavailable"
                assert events[0]["response"]["error"]["code"] == expected
                assert len(upstream.sent_text) == 1
                assert not upstream.closed
                assert len(fixture.connects) == 1
                client.portal.call(_assert_no_reserved_usage)
                assert [log["error_code"] for log in logs if log["status"] == "error"] == [expected]

                client.portal.call(_set_paused, fixture, False)
                _complete(websocket, _create([_DELTA], parent=_PARENT), "resp_after_reactivation")
                assert len(fixture.connects) == 1
                assert json.loads(upstream.sent_text[-1])["previous_response_id"] == _PARENT
                assert json.loads(upstream.sent_text[-1])["input"] == [_DELTA]
                assert "amber-moon-728" not in upstream.sent_text[-1]
        finally:
            client.portal.call(_set_paused, fixture, False)
    assert fixture.released_leases == ["retained-test-0"]


def test_pause_rejects_new_frame_without_interrupting_streaming_response(app_instance, monkeypatch):
    first_batch = _websocket_response_batch(_PARENT, completed=False)
    terminal = _completed_first_turn_upstream_batch(_PARENT)[-1]
    upstream = _SequencedUpstreamWebSocket([], deferred_message_batches=[first_batch])
    fixture = _RetainedSocketFixture(monkeypatch, [upstream], limited=True)
    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        try:
            with client.websocket_connect("/backend-api/codex/responses", headers=fixture.headers()) as websocket:
                websocket.send_json(_create([_FIRST]))
                for _ in first_batch:
                    websocket.receive_json()
                client.portal.call(_set_paused, fixture, True)
                websocket.send_json(_create([_DELTA]))
                events, disconnect = _receive_until_terminal(websocket)
                assert disconnect is None
                assert events[-1]["response"]["error"]["code"] == "preferred_account_unavailable"
                assert len(upstream.sent_text) == 1
                assert not upstream.closed
                client.portal.call(upstream._messages.put_nowait, terminal)
                events, disconnect = _receive_until_terminal(websocket)
                assert disconnect is None
                assert events[-1]["type"] == "response.completed"
                assert events[-1]["response"]["id"] == _PARENT
                client.portal.call(_assert_no_reserved_usage)
        finally:
            client.portal.call(_set_paused, fixture, False)
    assert fixture.released_leases == ["retained-test-0"]
