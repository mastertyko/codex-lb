from __future__ import annotations

import json
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket

from tests.integration.test_proxy_websocket_responses import (
    _completed_first_turn_upstream_batch,
    _FakeUpstreamMessage,
    _SequencedUpstreamWebSocket,
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


@pytest.mark.parametrize("ending", ["close", "error"])
def test_idle_upstream_loss_signals_reconnect_and_preserves_full_context(app_instance, monkeypatch, ending):
    first = _SequencedUpstreamWebSocket([], deferred_message_batches=[_completed_first_turn_upstream_batch(_PARENT)])
    next_socket = _SequencedUpstreamWebSocket(
        [], deferred_message_batches=[_completed_first_turn_upstream_batch("resp_recovered")]
    )
    fixture = _RetainedSocketFixture(monkeypatch, [first, next_socket])
    closed = threading.Event()
    close_codes = []
    original_close = WebSocket.close

    async def close(ws, code=1000, reason=None):
        close_codes.append(code)
        await original_close(ws, code, reason)
        closed.set()

    monkeypatch.setattr(WebSocket, "close", close)
    with TestClient(app_instance) as client:
        client.portal.call(fixture.prepare)
        with client.websocket_connect("/backend-api/codex/responses", headers=fixture.headers()) as downstream:
            _complete(downstream, _create([_FIRST]), _PARENT)
            client.portal.call(first._messages.put_nowait, _FakeUpstreamMessage(kind=ending, close_code=1000))
            assert closed.wait(2), "client was left connected to a lost upstream cache"
            assert close_codes[0] == 1012
        full_context = [_FIRST, {"role": "assistant", "content": [{"type": "output_text", "text": "ACK"}]}, _DELTA]
        with client.websocket_connect("/backend-api/codex/responses", headers=fixture.headers()) as downstream:
            _complete(downstream, _create(full_context), "resp_recovered")
            sent = json.loads(next_socket.sent_text[0])
            assert sent["input"] == full_context
            assert not sent.get("previous_response_id")
    assert fixture.released_leases == ["retained-test-0", "retained-test-1"]
