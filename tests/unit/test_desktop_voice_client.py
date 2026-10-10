from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import app.core.clients.desktop_voice as client_module
from app.core.clients.proxy import ProxyResponseError
from app.core.upstream_proxy import ResolvedProxyEndpoint, ResolvedUpstreamRoute

pytestmark = pytest.mark.unit


class _Body:
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0

    async def iter_chunked(self, _size):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk


class _Response:
    def __init__(self, *, status=201, chunks=(b"v=answer",)):
        self.status = status
        self.headers = {"Content-Type": "application/sdp", "Location": "/v1/realtime/calls/rtc_native"}
        self.content = _Body(chunks)
        self.exits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.exits += 1


def _request_args(**overrides):
    return {
        "payload": b"v=offer",
        "headers": {
            "Authorization": "Bearer caller-not-upstream",
            "ChatGPT-Account-Id": "caller-workspace",
            "X-Codex-LB-Key": "gateway-never-upstream",
            "Content-Type": "application/sdp",
            "x-codex-installation-id": "caller-installation",
            "originator": "codex_desktop",
            "OpenAI-Alpha": "quicksilver=v2",
            "X-OAI-Attestation": "caller-attestation",
        },
        "query_params": [("intent", "one"), ("intent", "two")],
        "access_token": "stored-access-token",
        "account_id": "stored-workspace",
        "route": None,
        "allow_direct_egress": True,
        "timeout_seconds": 1,
        **overrides,
    }


@pytest.fixture
def direct(monkeypatch):
    response = _Response()
    calls = []
    exits = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response

    @asynccontextmanager
    async def session():
        try:
            yield SimpleNamespace(post=post)
        finally:
            exits.append(True)

    monkeypatch.setattr(client_module, "lease_http_session", session)
    return response, calls, exits


@pytest.mark.parametrize("content_type", ["application/json", "application/sdp"])
async def test_native_creation_uses_fixed_origin_once_with_no_redirects_and_exact_owner(direct, content_type):
    response, calls, exits = direct
    arguments = _request_args()
    arguments["headers"]["Content-Type"] = content_type
    if content_type == "application/json":
        arguments["payload"] = b'{"sdp":"v=offer","session":{}}'
    payload = arguments["payload"]
    result = await client_module.create_desktop_voice_call(**arguments)
    assert result.status_code == 201 and result.body == b"v=answer"
    assert len(calls) == 1
    url, arguments = calls[0]
    assert url == "https://chatgpt.com/backend-api/wham/realtime/calls"
    assert arguments["data"] == payload
    assert arguments["params"] == [("intent", "one"), ("intent", "two")]
    assert arguments["allow_redirects"] is False
    headers = {key.lower(): value for key, value in arguments["headers"].items()}
    assert headers["authorization"] == "Bearer stored-access-token"
    assert headers["chatgpt-account-id"] == "stored-workspace"
    assert headers["x-codex-installation-id"] == "caller-installation"
    assert headers["content-type"] == content_type
    assert headers["originator"] == "codex_desktop"
    assert headers["openai-alpha"] == "quicksilver=v2"
    assert headers["x-oai-attestation"] == "caller-attestation"
    assert "caller-not-upstream" not in str(headers)
    assert "gateway-never-upstream" not in str(headers)
    assert response.exits == 1 and exits == [True]


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 404, 429, 500])
async def test_native_error_or_redirect_is_not_retried_read_or_leaked(direct, status):
    response, calls, exits = direct
    response.status = status
    response.content = _Body([b"raw private token and SDP"])
    with pytest.raises(ProxyResponseError) as error:
        await client_module.create_desktop_voice_call(**_request_args())
    assert error.value.status_code == (status if status >= 400 else 502)
    assert error.value.payload["error"]["code"] == "desktop_voice_call_failed"
    assert "raw private" not in str(error.value.payload)
    assert response.content.reads == 0
    assert len(calls) == 1 and response.exits == 1 and exits == [True]


async def test_native_creation_response_size_is_bounded(direct, monkeypatch):
    response, _, exits = direct
    response.content = _Body([b"1234", b"5678", b"should-not-read"])
    monkeypatch.setattr(client_module, "MAX_SSE_EVENT_BYTES", 6)
    with pytest.raises(ProxyResponseError) as error:
        await client_module.create_desktop_voice_call(**_request_args())
    assert error.value.status_code == 502
    assert response.content.reads == 2 and response.exits == 1 and exits == [True]


async def test_direct_egress_must_be_explicitly_allowed(direct):
    _, calls, _ = direct
    with pytest.raises(ValueError):
        await client_module.create_desktop_voice_call(**_request_args(allow_direct_egress=False))
    assert not calls


async def test_transport_failure_has_static_error_and_no_retry(monkeypatch):
    calls = []

    @asynccontextmanager
    async def failed_session():
        calls.append(True)
        raise RuntimeError("raw stored-token private-call-id")
        yield

    monkeypatch.setattr(client_module, "lease_http_session", failed_session)
    with pytest.raises(ProxyResponseError) as error:
        await client_module.create_desktop_voice_call(**_request_args())
    assert len(calls) == 1
    assert "raw" not in str(error.value.payload)
    assert error.value.__suppress_context__ is True


@pytest.mark.parametrize("outcome", ["ok", "denied", "cancelled"])
async def test_routed_native_creation_releases_response_and_client_once(monkeypatch, outcome):
    response = _Response(status=404 if outcome == "denied" else 201)
    requests, releases, closes = [], [], []
    sentinel_session = object()
    route = ResolvedUpstreamRoute(
        mode="account",
        pool_id="voice-egress",
        endpoint=ResolvedProxyEndpoint("endpoint", "http", "proxy.invalid", 8080),
    )

    class Client:
        def __init__(self, session):
            assert session is sentinel_session

        async def request(self, method, url, **kwargs):
            requests.append((method, url, kwargs))
            if outcome == "cancelled":
                raise asyncio.CancelledError
            return response

        async def close(self):
            closes.append(True)

    async def release(result):
        assert result is response
        releases.append(True)

    monkeypatch.setattr(client_module, "create_codex_session", lambda: sentinel_session)
    monkeypatch.setattr(client_module, "CodexClient", Client)
    monkeypatch.setattr(client_module, "release_codex_response", release)
    arguments = _request_args(route=route, allow_direct_egress=False)
    if outcome == "ok":
        assert (await client_module.create_desktop_voice_call(**arguments)).status_code == 201
    else:
        with pytest.raises(asyncio.CancelledError if outcome == "cancelled" else ProxyResponseError):
            await client_module.create_desktop_voice_call(**arguments)
    assert len(requests) == 1
    method, url, kwargs = requests[0]
    assert method == "POST" and url == "https://chatgpt.com/backend-api/wham/realtime/calls"
    assert kwargs["route"] is route
    assert kwargs["allow_redirects"] is False and kwargs["buffer_response"] is False
    assert closes == [True]
    assert releases == ([] if outcome == "cancelled" else [True])


@pytest.mark.parametrize("phase", ["request", "body"])
async def test_repeated_cancellation_does_not_abandon_routed_cleanup(monkeypatch, phase):
    io_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    finish_cleanup = asyncio.Event()
    releases, closes, close_completed = [], [], []
    response = _Response()
    route = ResolvedUpstreamRoute("account", "pool", ResolvedProxyEndpoint("endpoint", "http", "proxy.invalid", 80))

    class Body(_Body):
        async def iter_chunked(self, _size):
            io_started.set()
            await asyncio.Event().wait()
            yield b"unreachable"

    class Client:
        def __init__(self, _session):
            pass

        async def request(self, *_args, **_kwargs):
            if phase == "request":
                io_started.set()
                await asyncio.Event().wait()
            return response

        async def close(self):
            closes.append(True)
            if phase == "request":
                cleanup_started.set()
                await finish_cleanup.wait()
            close_completed.append(True)

    async def release(value):
        assert value is response
        releases.append(True)
        cleanup_started.set()
        await finish_cleanup.wait()

    response.content = Body(())
    monkeypatch.setattr(client_module, "create_codex_session", object)
    monkeypatch.setattr(client_module, "CodexClient", Client)
    monkeypatch.setattr(client_module, "release_codex_response", release)
    task = asyncio.create_task(client_module.create_desktop_voice_call(**_request_args(route=route)))
    try:
        await asyncio.wait_for(io_started.wait(), 1)
        task.cancel()
        await asyncio.wait_for(cleanup_started.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not close_completed
        finish_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert releases == ([True] if phase == "body" else [])
        assert closes == [True] and close_completed == [True]
    finally:
        finish_cleanup.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_routed_cleanup_attempts_both_closes_with_bounded_owned_tasks(monkeypatch):
    response = _Response()
    cancelled = []
    route = ResolvedUpstreamRoute("account", "pool", ResolvedProxyEndpoint("endpoint", "http", "proxy.invalid", 80))

    class Client:
        def __init__(self, _session):
            pass

        async def request(self, *_args, **_kwargs):
            return response

        async def close(self):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append("client")

    async def release(_value):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append("response")

    monkeypatch.setattr(client_module, "create_codex_session", object)
    monkeypatch.setattr(client_module, "CodexClient", Client)
    monkeypatch.setattr(client_module, "release_codex_response", release)
    monkeypatch.setattr(client_module, "_CLEANUP_TIMEOUT_SECONDS", 0.01)
    result = await asyncio.wait_for(client_module.create_desktop_voice_call(**_request_args(route=route)), 1)
    assert result.status_code == 201
    assert cancelled == ["response", "client"]
