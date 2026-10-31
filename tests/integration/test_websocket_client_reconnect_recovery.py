from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_proxy_websocket_responses import (
    _assert_previous_response_not_found_error,
    _assert_ws_single_response_lifecycle_completed,
    _completed_first_turn_upstream_batch,
    _receive_until_terminal,
    _SequencedUpstreamWebSocket,
    _TwoAccountWebSocketFailover,
    _ws_event,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(20)]


@pytest.mark.parametrize("model", ["gpt-5.4", "gpt-6.1-sol"])
def test_client_full_resend_recovers_short_stale_anchor_after_reconnect(app_instance, monkeypatch, model):
    """A lost upstream anchor fails closed; the client's full resend restores the session."""
    anchor_id = "resp_client_reconnect_anchor"
    recovered_id = "resp_client_reconnect_recovered"
    healthy_id = "resp_client_reconnect_healthy"
    first = _SequencedUpstreamWebSocket([], deferred_message_batches=[_completed_first_turn_upstream_batch(anchor_id)])
    rejected = _SequencedUpstreamWebSocket(
        [],
        deferred_message_batches=[
            [
                _ws_event(
                    {
                        "type": "error",
                        "status": 400,
                        "error": {
                            "type": "invalid_request_error",
                            "code": "previous_response_not_found",
                            "message": f"Previous response with id '{anchor_id}' not found.",
                            "param": "previous_response_id",
                        },
                    }
                )
            ]
        ],
    )
    recovered = _SequencedUpstreamWebSocket(
        [],
        deferred_message_batches=[
            _completed_first_turn_upstream_batch(recovered_id),
            _completed_first_turn_upstream_batch(healthy_id),
        ],
    )
    failover = _TwoAccountWebSocketFailover(first, recovered)
    failover.upstreams_by_account[failover.FIRST_ACCOUNT_ID].extend([rejected, recovered])
    failover.install(monkeypatch)
    headers = {"session_id": "client-reconnect-session", "thread-id": "client-reconnect-thread"}
    initial_input = failover.HISTORICAL_INPUT
    continuation = failover.FOLLOW_UP_INPUT
    complete_input = [
        initial_input,
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]},
        continuation,
    ]

    def create(input_items):
        return {**failover.response_create(input_items), "model": model}

    with TestClient(app_instance) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=headers) as websocket:
            websocket.send_json(create([initial_input]))
            events, disconnect = _receive_until_terminal(websocket)
            assert _assert_ws_single_response_lifecycle_completed(events, disconnect) == anchor_id

        with client.websocket_connect("/backend-api/codex/responses", headers=headers) as websocket:
            websocket.send_json({**create([continuation]), "previous_response_id": anchor_id})
            failed_events, disconnect = _receive_until_terminal(websocket)
            assert disconnect is None
            assert len(failed_events) == 1
            assert failed_events[0]["type"] == "response.failed"
            _assert_previous_response_not_found_error(failed_events[0]["response"]["error"])
            assert anchor_id not in json.dumps(failed_events)
            # No automatic retry may replay a delta without its missing context.
            assert failover.connect_accounts == [failover.FIRST_ACCOUNT_ID] * 2
            assert recovered.sent_text == []

        with client.websocket_connect("/backend-api/codex/responses", headers=headers) as websocket:
            websocket.send_json(create(complete_input))
            events, disconnect = _receive_until_terminal(websocket)
            assert _assert_ws_single_response_lifecycle_completed(events, disconnect) == recovered_id
            websocket.send_json({**create([continuation]), "previous_response_id": recovered_id})
            events, disconnect = _receive_until_terminal(websocket)
            assert _assert_ws_single_response_lifecycle_completed(events, disconnect) == healthy_id

    assert not failover.refused_connects
    assert failover.connect_accounts == [failover.FIRST_ACCOUNT_ID] * 3
    assert failover.required_at_connect[1] == failover.FIRST_ACCOUNT_ID
    assert all(excluded == set() for excluded in failover.excluded_at_connect)
    assert failover.stream_errors == []
    assert [entry["status"] for entry in failover.request_logs] == ["success", "error", "success", "success"]
    assert len(first.sent_text) == len(rejected.sent_text) == 1
    assert json.loads(rejected.sent_text[0])["previous_response_id"] == anchor_id
    recovery_payload = json.loads(recovered.sent_text[0])
    assert "previous_response_id" not in recovery_payload
    assert recovery_payload["input"] == complete_input
    assert len(recovered.sent_text) == 2
    assert json.loads(recovered.sent_text[1])["previous_response_id"] == recovered_id
