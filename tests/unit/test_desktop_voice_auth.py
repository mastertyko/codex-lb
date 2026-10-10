from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest

from app.core.auth import desktop_voice as auth
from app.core.upstream_proxy import ResolvedProxyEndpoint, ResolvedUpstreamRoute
from app.modules.api_keys.service import ApiKeyData

pytestmark = pytest.mark.unit


def _token(*, user: str | None = "user-desktop", workspace: str = "workspace-desktop", exp: float | None = None) -> str:
    nested = {"chatgpt_account_id": workspace, "chatgpt_account_user_id": "different-seat-id"}
    if user is not None:
        nested["chatgpt_user_id"] = user
    claims = {"https://api.openai.com/auth": nested, "sub": "different-sub", "exp": exp or time.time() + 3600}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


def _credentials(token: str | None = None) -> auth.DesktopVoiceCredentials:
    return auth.DesktopVoiceCredentials(
        access_token=token or _token(),
        chatgpt_account_id="workspace-desktop",
        api_key=cast(ApiKeyData, SimpleNamespace(id="key-private")),
        attestation="private-caller-attestation",
    )


class _Response:
    def __init__(self, status: int = 200, body: bytes | None = None, content_type: str = "application/json") -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.body = body if body is not None else b'{"plan_type":"pro","rate_limit":{"allowed":true}}'
        self.content = self
        self.released = False
        self.cancel = False

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        if self.cancel:
            raise asyncio.CancelledError
        for start in range(0, len(self.body), size):
            yield self.body[start : start + size]

    def release(self) -> None:
        self.released = True


@pytest.fixture
def verification(monkeypatch):
    state = SimpleNamespace(response=_Response(), calls=[], route=None, route_error=False, request_error=None)

    @asynccontextmanager
    async def database():
        yield object()

    async def resolve(_session, **kwargs):
        assert kwargs == {"account_id": None, "operation": "desktop_voice_identity", "scope": "service"}
        if state.route_error:
            raise RuntimeError("private route credentials")
        return state.route

    class Session:
        async def close(self):
            pass

        async def get(self, url, **kwargs):
            state.calls.append((url, kwargs))
            if state.request_error:
                raise state.request_error
            return state.response

    class RoutedClient:
        def __init__(self, session):
            pass

        async def request(self, method, url, **kwargs):
            assert method == "GET"
            state.calls.append((url, kwargs))
            return state.response

    monkeypatch.setattr(auth, "get_background_session", database)
    monkeypatch.setattr(auth, "resolve_upstream_route", resolve)
    monkeypatch.setattr(auth, "create_codex_session", Session)
    monkeypatch.setattr(auth, "CodexClient", RoutedClient)
    return state


def test_principal_uses_canonical_user_and_workspace_without_sub_alias_conflation():
    principal = auth.parse_desktop_voice_principal(_token(), "workspace-desktop")
    assert principal.user_id == "user-desktop"
    assert principal.workspace_id == "workspace-desktop"
    assert "user-desktop" not in repr(principal)
    credentials = _credentials()
    assert credentials.access_token not in repr(credentials)
    assert "key-private" not in repr(credentials)
    assert "private-caller-attestation" not in repr(credentials)


@pytest.mark.parametrize("token", ["bad", "a..b", "a.e30.b", "a.!@.b", "x" * 17000])
def test_malformed_selector_rejected(token):
    with pytest.raises(auth.DesktopVoiceAuthError):
        auth.parse_desktop_voice_principal(token)


def test_missing_canonical_user_expired_or_mismatched_account_rejected():
    for token, account in [(_token(user=None), None), (_token(exp=1), None), (_token(), "other")]:
        with pytest.raises(auth.DesktopVoiceAuthError):
            auth.parse_desktop_voice_principal(token, account)


@pytest.mark.asyncio
async def test_same_bearer_verified_once_at_fixed_origin(verification):
    credentials = _credentials()
    principal = await auth.verify_desktop_voice_principal(credentials)
    assert principal.workspace_id == "workspace-desktop"
    assert len(verification.calls) == 1
    url, kwargs = verification.calls[0]
    assert url == "https://chatgpt.com/backend-api/wham/usage"
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"] == {
        "Authorization": "Bearer " + credentials.access_token,
        "chatgpt-account-id": "workspace-desktop",
        "Accept": "application/json",
    }
    assert verification.response.released


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [204, 301, 302, 307, 308, 401, 403, 429, 500])
async def test_non_200_never_authenticates_or_retries(verification, status):
    verification.response.status = status
    with pytest.raises(auth.DesktopVoiceAuthError) as caught:
        await auth.verify_desktop_voice_principal(_credentials())
    assert caught.value.status_code == (401 if status in (401, 403) else 503)
    assert len(verification.calls) == 1
    assert verification.response.released


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{}",
        b"[]",
        b"secret: invalid",
        b'{"plan_type":"pro"}',
        b'{"plan_type":"pro","rate_limit":{}}',
        b" " * 65537,
    ],
)
async def test_empty_invalid_and_oversized_success_payload_rejected(verification, body):
    verification.response.body = body
    with pytest.raises(auth.DesktopVoiceAuthError) as caught:
        await auth.verify_desktop_voice_principal(_credentials())
    assert caught.value.status_code == 503
    assert caught.value.__context__ is None
    assert verification.response.released


@pytest.mark.asyncio
async def test_html_response_rejected_without_body_parsing(verification):
    verification.response.headers = {"Content-Type": "text/html"}
    with pytest.raises(auth.DesktopVoiceAuthError):
        await auth.verify_desktop_voice_principal(_credentials())


@pytest.mark.asyncio
async def test_service_egress_uses_one_selected_endpoint_without_fallback(verification):
    primary = ResolvedProxyEndpoint("primary", "https", "proxy.invalid", 443)
    fallback = ResolvedProxyEndpoint("fallback", "https", "fallback.invalid", 443)
    verification.route = ResolvedUpstreamRoute("default_pool", "pool", primary, (fallback,))
    await auth.verify_desktop_voice_principal(_credentials())
    assert len(verification.calls) == 1
    kwargs = verification.calls[0][1]
    assert kwargs["route"].endpoint is primary
    assert kwargs["route"].fallbacks == ()
    assert kwargs["allow_redirects"] is False
    assert kwargs["buffer_response"] is False


@pytest.mark.asyncio
async def test_route_failure_denies_without_direct_egress(verification):
    verification.route_error = True
    with pytest.raises(auth.DesktopVoiceAuthError) as caught:
        await auth.verify_desktop_voice_principal(_credentials())
    assert not verification.calls
    assert caught.value.__context__ is None


@pytest.mark.asyncio
async def test_transport_exception_does_not_escape_or_log_credentials(verification, caplog):
    verification.request_error = RuntimeError("private token upstream body")
    with pytest.raises(auth.DesktopVoiceAuthError) as caught:
        await auth.verify_desktop_voice_principal(_credentials())
    assert caught.value.__context__ is None
    assert "private token" not in str(caught.value.payload)
    assert "private token" not in caplog.text


@pytest.mark.asyncio
async def test_cancelled_body_releases_response_and_propagates_cancellation(verification):
    verification.response.cancel = True
    with pytest.raises(asyncio.CancelledError):
        await auth.verify_desktop_voice_principal(_credentials())
    assert verification.response.released


@pytest.mark.asyncio
async def test_repeated_cancellation_finishes_verifier_session_cleanup(verification, monkeypatch):
    request_started = asyncio.Event()
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    closed = []

    class Session:
        async def close(self):
            close_started.set()
            await allow_close.wait()
            closed.append(True)

        async def get(self, *_args, **_kwargs):
            request_started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(auth, "create_codex_session", Session)
    task = asyncio.create_task(auth.verify_desktop_voice_principal(_credentials()))
    try:
        await asyncio.wait_for(request_started.wait(), 1)
        task.cancel()
        await asyncio.wait_for(close_started.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        allow_close.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert closed == [True]
    finally:
        allow_close.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_verifier_cleanup_bounds_response_and_session_separately(verification, monkeypatch):
    cancelled = []

    class Session:
        async def get(self, *_args, **_kwargs):
            return verification.response

        async def close(self):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append("session")

    async def release(_response):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append("response")

    monkeypatch.setattr(auth, "create_codex_session", Session)
    monkeypatch.setattr(auth, "release_codex_response", release)
    monkeypatch.setattr(auth, "_VERIFY_CLEANUP_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(auth.DesktopVoiceAuthError) as error:
        await asyncio.wait_for(auth.verify_desktop_voice_principal(_credentials()), 1)
    assert error.value.status_code == 503
    assert cancelled == ["response", "session"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_phase", ["request", "cleanup"])
async def test_cancellation_survives_verifier_cleanup_timeout(verification, monkeypatch, cancel_phase):
    request_started = asyncio.Event()
    close_started = asyncio.Event()
    close_finished = []

    class Session:
        async def get(self, *_args, **_kwargs):
            request_started.set()
            if cancel_phase == "request":
                await asyncio.Event().wait()
            return verification.response

        async def close(self):
            close_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                close_finished.append(True)

    monkeypatch.setattr(auth, "create_codex_session", Session)
    monkeypatch.setattr(auth, "_VERIFY_CLEANUP_TIMEOUT_SECONDS", 0.02)
    task = asyncio.create_task(auth.verify_desktop_voice_principal(_credentials()))
    try:
        if cancel_phase == "request":
            await asyncio.wait_for(request_started.wait(), 1)
            task.cancel()
        await asyncio.wait_for(close_started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert close_finished == [True]
        assert task.cancelled()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
