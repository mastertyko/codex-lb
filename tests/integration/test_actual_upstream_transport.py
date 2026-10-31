from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import cast

import aiohttp
import pytest
from sqlalchemy import select

import app.core.clients.proxy as upstream
import app.modules.proxy._service.streaming.retry as retry
import app.modules.proxy.service as proxy
from app.core.errors import openai_error
from app.db.models import RequestLog
from app.db.session import SessionLocal
from tests.integration.test_ultrafast_cost_accounting import prepare_account, read_log

pytestmark = pytest.mark.integration


class _Content:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class _SsePostResponse:
    status = 200
    headers = {"content-type": "text/event-stream"}

    def __init__(self, chunks):
        self.content = _Content(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _SseSession:
    def __init__(self, response):
        self.response = response

    def post(self, *args, **kwargs):
        return self.response


class _WsMessage:
    def __init__(self, kind, data=None):
        self.type = kind
        self.data = data


class _WsResponse:
    def __init__(self, messages):
        self.messages = iter(messages)
        self._response = SimpleNamespace(status=101)
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
        return False

    async def receive(self):
        return next(self.messages, _WsMessage(aiohttp.WSMsgType.CLOSED))

    async def send_str(self, data):
        return None

    async def close(self):
        self.closed = True

    def exception(self):
        return None


class _WsSession:
    def __init__(self, response):
        self.response = response

    def ws_connect(self, *args, **kwargs):
        return self.response


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
@pytest.mark.parametrize(
    "mode,expected",
    [
        ("http", "http"),
        ("websocket", "websocket"),
        ("fallback", "http"),
        ("failed_ws", "websocket"),
        ("pre_dispatch", None),
    ],
)
async def test_request_log_records_actual_transport(async_client, monkeypatch, path, mode, expected):
    await prepare_account(async_client, monkeypatch)
    response_id = "resp_transport_observed"
    event = {
        "type": "response.completed",
        "response": {"id": response_id, "usage": {"input_tokens": 1, "output_tokens": 1}},
    }
    # Exercise the raw HTTP-stream path, with real core transport selection and fallback.
    monkeypatch.setattr(retry, "_http_bridge_allowed_by_transport_policy", lambda *a, **k: False)
    monkeypatch.setattr(upstream, "discover_native_egress_client", lambda: None)
    monkeypatch.setattr(
        upstream, "get_model_registry", lambda: SimpleNamespace(prefers_websockets=lambda _: mode != "http")
    )
    monkeypatch.setattr(retry, "_resolve_stream_transport", lambda **k: "http" if mode == "http" else "websocket")
    session = _SseSession(_SsePostResponse([("data: " + json.dumps(event) + "\n\n").encode()]))
    if mode == "websocket":
        session = _WsSession(_WsResponse([_WsMessage(aiohttp.WSMsgType.TEXT, json.dumps(event))]))
    if mode in ("fallback", "failed_ws"):

        async def rejected(**kwargs):
            raise aiohttp.WSServerHandshakeError(
                cast(aiohttp.RequestInfo, SimpleNamespace(real_url="wss://example.test")),
                (),
                status=426 if mode == "fallback" else 400,
                message="rejected",
            )

        monkeypatch.setattr(upstream, "_open_upstream_websocket", rejected)
    if mode == "pre_dispatch":

        def fail_before_connect(*a, **k):
            raise upstream.ProxyResponseError(413, openai_error("invalid_request_error", "Too large"))

        monkeypatch.setattr(upstream, "_prepare_websocket_response_create_payload", fail_before_connect)
    observations = []
    monkeypatch.setattr(retry, "_record_upstream_transport_decision", lambda **k: observations.append(k))

    async def stream(payload, headers, token, account_id, **kwargs):
        kwargs["session"] = session
        kwargs["allow_direct_egress"] = True
        async for chunk in upstream.stream_responses(payload, headers, token, account_id, **kwargs):
            yield chunk

    monkeypatch.setattr(proxy, "core_stream_responses", stream)
    response = await async_client.post(
        path, json={"model": "gpt-6.1-sol", "input": [], "stream": True, "prompt_cache_key": "transport-observation"}
    )
    if mode in ("http", "websocket", "fallback"):
        assert response.status_code == 200, response.text
        assert "response.completed" in response.text
        log = await read_log(response_id)
    else:
        async with SessionLocal() as db:
            logs = list((await db.scalars(select(RequestLog))).all())
            assert logs
            log = logs[-1]
    assert log.transport == "http"
    assert log.upstream_transport == expected
    api_result = await async_client.get("/api/request-logs")
    assert api_result.status_code == 200
    entry = next(r for r in api_result.json()["requests"] if r["requestId"] == log.request_id)
    assert entry["upstreamTransport"] == expected
    assert observations and observations[-1]["upstream_transport"] == expected


async def test_concurrent_requests_keep_transport_observations_isolated(async_client, monkeypatch):
    await prepare_account(async_client, monkeypatch)
    monkeypatch.setattr(retry, "_http_bridge_allowed_by_transport_policy", lambda *a, **k: False)
    monkeypatch.setattr(upstream, "discover_native_egress_client", lambda: None)
    started = 0
    both_started = asyncio.Event()

    async def stream(payload, headers, token, account_id, **kwargs):
        nonlocal started
        transport = payload.instructions
        event = {"type": "response.completed", "response": {"id": "resp_concurrent_" + transport}}
        if transport == "http":
            session = _SseSession(_SsePostResponse([("data: " + json.dumps(event) + "\n\n").encode()]))
        else:
            session = _WsSession(_WsResponse([_WsMessage(aiohttp.WSMsgType.TEXT, json.dumps(event))]))
        kwargs["session"] = session
        kwargs["allow_direct_egress"] = True
        kwargs["upstream_stream_transport_override"] = transport
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=5)
        async for chunk in upstream.stream_responses(payload, headers, token, account_id, **kwargs):
            yield chunk

    monkeypatch.setattr(proxy, "core_stream_responses", stream)
    responses = await asyncio.gather(
        *[
            async_client.post(
                "/backend-api/codex/responses",
                json={
                    "model": "gpt-6.1-sol",
                    "instructions": transport,
                    "input": [],
                    "stream": True,
                },
            )
            for transport in ("http", "websocket")
        ]
    )
    assert all(r.status_code == 200 for r in responses)
    for transport in ("http", "websocket"):
        assert (await read_log("resp_concurrent_" + transport)).upstream_transport == transport
