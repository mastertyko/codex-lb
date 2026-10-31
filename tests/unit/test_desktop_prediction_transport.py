from __future__ import annotations

import asyncio
import json
import logging

import pytest
from pydantic import ValidationError

from app.core.auth.desktop_diagnostics import LOGGER_NAME, trace_request
from app.core.clients import desktop_predictions as http
from app.core.clients import proxy_websocket as ws
from app.core.clients.proxy import ProxyResponseError
from app.core.config.settings import Settings
from app.core.openai.requests import ResponsesRequest

pytestmark = pytest.mark.unit


class Response:
    status = 200
    headers = {"Content-Type": "text/event-stream"}

    def __init__(self):
        self.content = self
        self.released = False

    async def iter_chunked(self, size):
        yield b'data: {"type":"response.completed"}\n'
        yield b"\n"

    def release(self):
        self.released = True


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("status", [200, 403])
async def test_http_diagnostics_report_status_without_headers_or_body(monkeypatch, caplog, status):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    response = Response()
    response.status = status
    monkeypatch.setattr(http, "create_codex_session", lambda: Session(response))
    with trace_request("http"):
        stream = http.stream_prediction(
            ResponsesRequest(model="gpt-6.1-sol", instructions="private-instruction", input=[]),
            {},
            "private-bearer",
            "private-workspace",
            route=None,
            timeout_seconds=1,
        )
        if status == 200:
            _ = [event async for event in stream]
        else:
            with pytest.raises(ProxyResponseError):
                _ = [event async for event in stream]
    events = [json.loads(record.message) for record in caplog.records if record.name == LOGGER_NAME]
    assert any(event["event"] == "upstream_status" and event["status"] == status for event in events)
    assert "private" not in json.dumps(events)


@pytest.mark.parametrize("status", [200, 302, 401, 500])
async def test_actual_http_transport_fixed_destination_and_no_redirects(monkeypatch, status):
    response = Response()
    response.status = status
    session = Session(response)
    monkeypatch.setattr(http, "create_codex_session", lambda: session)
    payload = ResponsesRequest(model="gpt-6.1-sol", instructions="", input=[], stream=True)
    stream = http.stream_prediction(
        payload,
        {"originator": "codex_cli_rs", "x-oai-attestation": "private-attestation"},
        "private-bearer",
        "private-workspace",
        route=None,
        timeout_seconds=1,
    )
    if status == 200:
        assert [event async for event in stream] == ['data: {"type":"response.completed"}\n\n']
    else:
        with pytest.raises(ProxyResponseError) as exc:
            _ = [event async for event in stream]
        assert "private" not in str(exc.value.payload)
    assert session.closed and response.released
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == "https://chatgpt.com/backend-api/codex/responses"
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["Authorization"] == "Bearer private-bearer"
    assert kwargs["headers"]["chatgpt-account-id"] == "private-workspace"


async def test_cancelled_http_closes_owned_session(monkeypatch):
    session = Session(Response())
    entered = asyncio.Event()

    async def waiting(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(session, "post", waiting)
    monkeypatch.setattr(http, "create_codex_session", lambda: session)
    stream = http.stream_prediction(
        ResponsesRequest(model="gpt-6.1-sol", instructions="", input=[]),
        {},
        "bearer",
        "workspace",
        route=None,
        timeout_seconds=1,
    )

    async def receive():
        return await anext(stream)

    task = asyncio.create_task(receive())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session.closed


async def test_actual_websocket_builder_has_caller_policy(monkeypatch):
    calls = []

    async def connect(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(ws, "_connect_upstream_websocket", connect)
    await ws.connect_responses_websocket(
        {}, "private", "workspace", base_url=http.PREDICTION_BASE_URL, caller_owned=True, allow_direct_egress=True
    )
    assert calls[0][1]["url"] == "wss://chatgpt.com/backend-api/codex/responses"
    policy = calls[0][1]["policy"]
    assert not policy.archive_payloads
    assert not policy.retry_handshake_status
    assert not policy.retry_routed_network_errors
    assert policy.credential_safe_connect_errors


def test_grants_default_closed_and_reject_ambiguous_bindings():
    assert Settings(_env_file=None).desktop_oauth_grants == []
    grant = {"user_id": "user", "workspace_id": "workspace", "api_key_id": "key"}
    for values in ([grant, grant], [grant, {**grant, "user_id": "other"}], [{**grant, "user_id": " user"}]):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, desktop_oauth_grants=values)
