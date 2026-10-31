"""Retired Desktop Voice must not reach authentication, owners or upstreams."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from app.core.middleware import desktop_credentials, desktop_oauth
from app.modules.proxy.service import ProxyService

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("prefix", ["/backend-api/codex/desktop-voice", "/backend-api/codex/v1/desktop-voice"])
@pytest.mark.parametrize("suffix", ["", "/", "/realtime/calls", "/live/rtc_private", "/realtime"])
@pytest.mark.parametrize("credential", ["absent", "native", "split", "legacy"])
def test_retired_routes_deny_before_any_dispatch_and_redact_server_scope(
    app_instance, monkeypatch, transport, prefix, suffix, credential
):
    async def forbidden(*args, **kwargs):
        pytest.fail("retired Voice reached authentication or upstream dispatch")

    monkeypatch.setattr(desktop_oauth, "authenticate_desktop_oauth", forbidden)
    monkeypatch.setattr(desktop_credentials, "validate_required_proxy_api_key_authorization", forbidden)
    monkeypatch.setattr(ProxyService, "proxy_realtime_live_websocket", forbidden)
    observed = []

    async def observe(scope, receive, send):
        async def capture(message):
            observed.append((scope["path"], scope.get("raw_path"), scope["query_string"], scope["headers"]))
            await send(message)

        await app_instance(scope, receive, capture)

    headers = {"Cookie": "private-cookie", "X-OAI-Attestation": "private-attestation"}
    if credential in {"native", "split"}:
        headers["Authorization"] = "Bearer header.private.signature"
        headers["ChatGPT-Account-Id"] = "private-workspace"
    if credential == "split":
        headers["X-Codex-LB-Key"] = "private-gateway-key"
    if credential == "legacy":
        headers["Authorization"] = "Bearer private-api-key"
    private_values = tuple(headers.values())
    path = prefix + suffix + "?call_id=rtc_private&private_query=hidden"
    client = TestClient(observe)
    if transport == "http":
        response = client.post(path, headers=headers, content=b"private-sdp")
    else:
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(path, headers=headers):
                pytest.fail("retired Voice handshake was accepted")
        response = denied.value
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "desktop_voice_retired"
    assert observed
    for private in ("rtc_private", "private_query", *private_values, "private-sdp"):
        assert private not in str(observed)
        assert private not in response.text


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("prefix", ["/backend-api/codex", "/backend-api/codex/v1", "/v1"])
@pytest.mark.parametrize("suffix", ["/realtime", "/realtime/calls", "/live/rtc_private"])
def test_unsupported_native_realtime_redacts_server_scope(app_instance, monkeypatch, transport, prefix, suffix):
    async def forbidden(*args, **kwargs):
        pytest.fail("native realtime reached online verification")

    monkeypatch.setattr(desktop_oauth, "authenticate_desktop_oauth", forbidden)
    observed = []

    async def observe(scope, receive, send):
        async def capture(message):
            observed.append((scope["path"], scope.get("raw_path"), scope["query_string"], scope["headers"]))
            await send(message)

        await app_instance(scope, receive, capture)

    client = TestClient(observe)
    path = prefix + suffix + "?call_id=rtc_private&private_query=hidden"
    headers = {"Authorization": "Bearer header.private.signature"}
    if transport == "http":
        response = client.post(path, headers=headers)
    else:
        with pytest.raises(WebSocketDenialResponse) as denied:
            with client.websocket_connect(path, headers=headers):
                pytest.fail("unsupported native realtime was accepted")
        response = denied.value
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "desktop_oauth_denied"
    for private in ("rtc_private", "private_query", "header.private.signature"):
        assert private not in str(observed)
