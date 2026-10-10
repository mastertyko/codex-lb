from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from starlette.testclient import WebSocketDenialResponse

import app.core.clients.proxy_websocket as websocket_transport
import app.modules.proxy._service.desktop_voice as voice_service
import app.modules.proxy.load_balancer as balancer_module
from app.core.auth.desktop_voice import DesktopVoiceAuthError, DesktopVoicePrincipal
from app.core.clients.proxy import CodexControlResponse, ProxyResponseError
from app.core.clients.proxy_websocket import UpstreamWebSocketMessage
from app.core.crypto import TokenEncryptor
from app.core.errors import openai_error
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, ApiKey, StickySession
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.proxy._load_balancer.types import AccountConcurrencyCaps
from app.modules.proxy.load_balancer import LoadBalancer
from app.modules.proxy.service import ProxyService
from tests.integration.off_loop_test_client import off_loop_test_client

pytestmark = pytest.mark.integration

PREFIX = "/backend-api/codex/desktop-voice"
OWNER_ID = "voice-owner"
USER_ID = "voice-user"
WORKSPACE_ID = "voice-workspace"

ACCEPTED_ATTESTATIONS = [
    pytest.param("private-caller-attestation", id="opaque"),
    pytest.param('{"v":1,"s":0,"t":"v1.opaque-client-payload"}', id="native-success"),
    pytest.param('{"v":1,"s":0,"t":""}', id="native-empty-token"),
    pytest.param('{"t":"opaque,token","s":0,"v":1}', id="native-reordered-opaque-token"),
    *(pytest.param(f'{{"v":1,"s":{status}}}', id=f"native-failure-{status}") for status in range(1, 5)),
]


def _token(*, user_id=USER_ID, workspace_id=WORKSPACE_ID, expires=None) -> str:
    claims = {
        "https://api.openai.com/auth": {
            "chatgpt_user_id": user_id,
            "chatgpt_account_id": workspace_id,
            "chatgpt_account_user_id": "different-seat-alias",
        },
        "sub": "different-sub-alias",
        "exp": time.time() + 3600 if expires is None else expires,
    }
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{body}.stored-signature"


async def _add_account(
    account_id=OWNER_ID, *, user_id=USER_ID, workspace_id=WORKSPACE_ID, status=AccountStatus.PAUSED, token=None
) -> str:
    access_token = token or _token(user_id=user_id, workspace_id=workspace_id)
    encryptor = TokenEncryptor()
    async with SessionLocal() as session:
        session.add(
            Account(
                id=account_id,
                chatgpt_user_id=user_id,
                chatgpt_account_id=workspace_id,
                email=f"{account_id}@example.invalid",
                plan_type="pro",
                status=status,
                last_refresh=utcnow(),
                access_token_encrypted=encryptor.encrypt(access_token),
                refresh_token_encrypted=encryptor.encrypt("stored-refresh-secret"),
                id_token_encrypted=encryptor.encrypt("stored-id-secret"),
            )
        )
        await session.commit()
    return access_token


class _EchoPeer:
    def __init__(self, *, selected_subprotocol=None) -> None:
        self.close_calls = []
        self.messages = asyncio.Queue()
        self.selected_subprotocol = selected_subprotocol

    async def send_text(self, text: str) -> None:
        await self.messages.put(UpstreamWebSocketMessage(kind="text", text=text))

    async def send_bytes(self, data: bytes) -> None:
        await self.messages.put(UpstreamWebSocketMessage(kind="binary", data=data))

    async def receive(self) -> UpstreamWebSocketMessage:
        return await self.messages.get()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_calls.append((code, reason))

    def response_header(self, name: str) -> str | None:
        return self.selected_subprotocol if name.lower() == "sec-websocket-protocol" else None


@dataclass
class _Harness:
    app: Any
    client: Any
    headers: dict[str, str]
    stored_token: str
    key_id: str
    connections: list = field(default_factory=list)
    created: list = field(default_factory=list)
    releases: list = field(default_factory=list)
    verified: list = field(default_factory=list)
    peers: list = field(default_factory=list)


@pytest_asyncio.fixture
async def voice_harness(app_instance, async_client, monkeypatch):
    stored_token = await _add_account()
    key_response = await async_client.post("/api/api-keys/", json={"name": "desktop-voice-test"})
    assert key_response.status_code == 200
    key = key_response.json()
    harness = _Harness(
        app=app_instance,
        client=async_client,
        headers={
            "Authorization": "Bearer caller-oauth-secret",
            "X-Codex-LB-Key": key["key"],
            "ChatGPT-Account-Id": WORKSPACE_ID,
            "x-codex-installation-id": "caller-installation",
            "originator": "codex_desktop",
            "User-Agent": "codex_desktop/0.162.0-test",
            "OpenAI-Alpha": "quicksilver=v2",
            "Thread-Id": "private-thread-context",
            "Session-Id": "private-session-context",
            "X-OAI-Attestation": "private-caller-attestation",
            "Content-Type": "application/sdp",
        },
        stored_token=stored_token,
        key_id=key["id"],
    )

    async def verified(credentials):
        harness.verified.append(credentials)
        assert credentials.access_token == "caller-oauth-secret"
        return DesktopVoicePrincipal(USER_ID, WORKSPACE_ID)

    async def route(_self, _account, *, operation):
        assert operation == "desktop_voice"
        return None

    async def connected(headers, access_token, account_id, *, url, **kwargs):
        peer = _EchoPeer(selected_subprotocol="voice-v3" if kwargs["subprotocols"] else None)
        harness.peers.append(peer)
        harness.connections.append((headers, access_token, account_id, url, kwargs))
        return peer

    async def created(**kwargs):
        harness.created.append(kwargs)
        return CodexControlResponse(
            201, b"v=answer\r\n", {"Location": "/v1/realtime/calls/rtc_created", "Content-Type": "application/sdp"}
        )

    original_release = LoadBalancer.release_account_lease

    async def release(self, lease):
        harness.releases.append(lease)
        await original_release(self, lease)

    async def no_pool(*args, **kwargs):
        raise AssertionError("Desktop Voice must never select from the model pool")

    monkeypatch.setattr(voice_service, "verify_desktop_voice_principal", verified)
    monkeypatch.setattr(voice_service, "create_desktop_voice_call", created)
    monkeypatch.setattr(ProxyService, "_resolve_upstream_route_for_account", route)
    monkeypatch.setattr(websocket_transport, "_connect_upstream_websocket", connected)
    monkeypatch.setattr(LoadBalancer, "release_account_lease", release)
    monkeypatch.setattr(LoadBalancer, "select_account", no_pool)
    return harness


async def _denied(harness, path=PREFIX + "/live/rtc_private", *, status=503, code=None):
    async with off_loop_test_client(harness.app) as client:
        with pytest.raises(WebSocketDenialResponse) as error:
            with client.websocket_connect(path, headers=harness.headers):
                pytest.fail("unavailable owner must not establish a Voice connection")
        response = error.value
        assert response.status_code == status, response.text
        if code is not None:
            assert response.json()["error"]["code"] == code
        for secret in ("caller-oauth-secret", harness.stored_token, "rtc_private", USER_ID, WORKSPACE_ID):
            assert secret not in response.text
    return response


@pytest.mark.parametrize("attestation", ACCEPTED_ATTESTATIONS)
@pytest.mark.parametrize(
    ("path", "upstream_suffix"),
    [
        (
            "/live/rtc_external?intent=first&intent=second&empty=",
            "/live/rtc_external?intent=first&intent=second&empty=",
        ),
        ("/rtc_external?intent=first&intent=second&empty=", "/live/rtc_external?intent=first&intent=second&empty="),
        (
            "/realtime?intent=first&call_id=rtc_external&intent=second&empty=",
            "/realtime?intent=first&intent=second&empty=&call_id=rtc_external",
        ),
    ],
)
async def test_paused_exact_owner_uses_stored_token_and_preserves_protocol(
    voice_harness, path, upstream_suffix, caplog, attestation
):
    h = voice_harness
    h.headers["X-OAI-Attestation"] = attestation
    caplog.set_level(logging.WARNING, logger="app.core.middleware.desktop_voice")
    await _add_account("same-workspace-different-seat", user_id="other-user", status=AccountStatus.ACTIVE)
    async with off_loop_test_client(h.app) as client:
        with client.websocket_connect(PREFIX + path, headers=h.headers, subprotocols=["voice-v3"]) as socket:
            assert socket.accepted_subprotocol == "voice-v3"
            socket.send_text("private-text")
            assert socket.receive_text() == "private-text"
            socket.send_bytes(b"private-audio")
            assert socket.receive_bytes() == b"private-audio"
        assert len(h.connections) == 1
        inbound, access_token, account_id, url, kwargs = h.connections[0]
        assert access_token == h.stored_token
        assert account_id == WORKSPACE_ID
        assert url == "wss://api.openai.com/v1" + upstream_suffix
        assert inbound["x-codex-installation-id"] == "caller-installation"
        assert inbound["originator"] == "codex_desktop"
        assert inbound["user-agent"] == "codex_desktop/0.162.0-test"
        assert inbound["openai-alpha"] == "quicksilver=v2"
        assert inbound["thread-id"] == "private-thread-context"
        assert inbound["session-id"] == "private-session-context"
        assert inbound["x-oai-attestation"] == attestation
        assert "x-codex-lb-key" not in inbound
        assert "caller-oauth-secret" not in str(inbound)
        assert kwargs["route"] is None and kwargs["allow_direct_egress"] is True
        assert len(h.peers[0].close_calls) == 1
        assert len(h.releases) == 1 and h.releases[0].account_id == OWNER_ID
        assert h.releases[0].api_key_id == h.key_id
        assert client.portal is not None
        assert client.portal.call(
            get_proxy_service_for_app(h.app)._load_balancer.account_pressure_snapshot, OWNER_ID
        ) == (0, 0, 0.0)
    async with SessionLocal() as session:
        owner = await session.get(Account, OWNER_ID)
        assert owner is not None
        assert owner.status == AccountStatus.PAUSED
        assert await session.scalar(select(func.count()).select_from(StickySession)) == 0
    assert not [record for record in caplog.records if record.name == "app.core.middleware.desktop_voice"]


@pytest.mark.parametrize("attestation", ACCEPTED_ATTESTATIONS)
async def test_app_server_creation_preserves_paused_owner_without_legacy_binding(voice_harness, caplog, attestation):
    h = voice_harness
    h.headers["X-OAI-Attestation"] = attestation
    caplog.set_level(logging.WARNING, logger="app.core.middleware.desktop_voice")
    offer = b'{"sdp":"v=offer","session":{"type":"realtime"}}'
    response = await h.client.post(
        PREFIX + "/realtime/calls?intent=one&intent=two",
        headers={**h.headers, "Content-Type": "application/json"},
        content=offer,
    )
    assert response.status_code == 201, response.text
    assert response.content == b"v=answer\r\n"
    assert response.headers["location"] == "/v1/realtime/calls/rtc_created"
    assert len(h.created) == 1
    call = h.created[0]
    assert call["access_token"] == h.stored_token
    assert call["account_id"] == WORKSPACE_ID
    assert call["payload"] == offer and call["headers"]["content-type"] == "application/json"
    assert call["headers"]["x-codex-installation-id"] == "caller-installation"
    assert call["headers"]["x-oai-attestation"] == attestation
    assert call["query_params"] == [("intent", "one"), ("intent", "two")]
    assert len(h.releases) == 1
    async with SessionLocal() as session:
        owner = await session.get(Account, OWNER_ID)
        assert owner is not None
        assert owner.status == AccountStatus.PAUSED
        assert await session.scalar(select(func.count()).select_from(StickySession)) == 0
    assert not [record for record in caplog.records if record.name == "app.core.middleware.desktop_voice"]


@pytest.mark.parametrize(
    "state",
    [
        AccountStatus.DEACTIVATED,
        AccountStatus.REAUTH_REQUIRED,
        AccountStatus.RATE_LIMITED,
        AccountStatus.QUOTA_EXCEEDED,
    ],
)
async def test_unavailable_owner_states_never_use_a_stored_token(voice_harness, state):
    h = voice_harness
    async with SessionLocal() as session:
        await session.execute(update(Account).where(Account.id == OWNER_ID).values(status=state))
        await session.commit()
    await _denied(h, code="desktop_voice_owner_unavailable")
    assert not h.connections and not h.releases


@pytest.mark.parametrize("mutation", ["unknown-user", "unknown-workspace", "missing-user", "soft-deleted", "ambiguous"])
async def test_owner_requires_exact_unambiguous_nondeleted_user_and_workspace(voice_harness, mutation):
    h = voice_harness
    if mutation == "ambiguous":
        await _add_account("duplicate-owner")
    else:
        changes = {
            "unknown-user": {"chatgpt_user_id": "other-user"},
            "unknown-workspace": {"chatgpt_account_id": "other-workspace"},
            "missing-user": {"chatgpt_user_id": None},
            "soft-deleted": {"delete_requested_at": utcnow()},
        }[mutation]
        async with SessionLocal() as session:
            await session.execute(update(Account).where(Account.id == OWNER_ID).values(**changes))
            await session.commit()
    await _denied(h, status=404, code="desktop_voice_owner_not_found")
    assert not h.connections and not h.releases


async def test_out_of_scope_owner_is_denied_without_pool_fallback(voice_harness):
    h = voice_harness
    await _add_account("allowed-other-owner", user_id="other-user")
    response = await h.client.patch(f"/api/api-keys/{h.key_id}", json={"assignedAccountIds": ["allowed-other-owner"]})
    assert response.status_code == 200, response.text
    await _denied(h, code="desktop_voice_owner_unavailable")
    assert not h.connections and not h.releases


@pytest.mark.parametrize("mutation", ["deactivate", "reauth", "delete", "key-scope", "key-revoke", "duplicate"])
async def test_recheck_after_routing_awaits_prevents_credential_race(voice_harness, monkeypatch, mutation):
    h = voice_harness

    async def route(_self, _account, *, operation):
        async with SessionLocal() as session:
            if mutation == "key-scope":
                await session.execute(
                    update(ApiKey).where(ApiKey.id == h.key_id).values(account_assignment_scope_enabled=True)
                )
            elif mutation == "key-revoke":
                await session.execute(update(ApiKey).where(ApiKey.id == h.key_id).values(is_active=False))
            elif mutation == "duplicate":
                await _add_account("racing-duplicate")
            else:
                changes = {
                    "deactivate": {"status": AccountStatus.DEACTIVATED},
                    "reauth": {"chatgpt_user_id": "new-user"},
                    "delete": {"delete_requested_at": utcnow()},
                }[mutation]
                await session.execute(update(Account).where(Account.id == OWNER_ID).values(**changes))
            await session.commit()
        return None

    monkeypatch.setattr(ProxyService, "_resolve_upstream_route_for_account", route)
    await _denied(h, status=401 if mutation == "key-revoke" else 503)
    assert not h.connections and len(h.releases) == 1


@pytest.mark.parametrize(
    "token,code",
    [
        ("malformed", "desktop_voice_owner_token_invalid"),
        (_token(user_id="wrong-user"), "desktop_voice_owner_token_invalid"),
        (_token(expires=1), "desktop_voice_owner_token_expired"),
    ],
)
async def test_stored_token_must_match_principal_and_be_current(voice_harness, token, code):
    h = voice_harness
    async with SessionLocal() as session:
        await session.execute(
            update(Account).where(Account.id == OWNER_ID).values(access_token_encrypted=TokenEncryptor().encrypt(token))
        )
        await session.commit()
    await _denied(h, code=code)
    assert not h.connections and len(h.releases) == 1


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("attestation", ACCEPTED_ATTESTATIONS)
async def test_caller_verification_failure_precedes_stored_decryption(
    voice_harness, monkeypatch, transport, attestation
):
    h = voice_harness
    h.headers["X-OAI-Attestation"] = attestation
    async with SessionLocal() as session:
        owner = await session.get(Account, OWNER_ID)
        assert owner is not None
        encrypted_owner_token = owner.access_token_encrypted
    original_decrypt = TokenEncryptor.decrypt

    async def rejected(_credentials):
        raise DesktopVoiceAuthError()

    def must_not_decrypt(self, value):
        if value == encrypted_owner_token:
            pytest.fail("stored token must remain encrypted for an unauthenticated caller")
        return original_decrypt(self, value)

    monkeypatch.setattr(voice_service, "verify_desktop_voice_principal", rejected)
    monkeypatch.setattr(TokenEncryptor, "decrypt", must_not_decrypt)
    if transport == "http":
        response = await h.client.post(PREFIX + "/realtime/calls", headers=h.headers, content=b"private-offer")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "desktop_voice_identity_invalid"
    else:
        await _denied(h, status=401, code="desktop_voice_identity_invalid")
    assert not h.connections and not h.created and not h.releases


@pytest.mark.parametrize(
    "path", ["/realtime", "/realtime?call_id=rtc_private&call_id=rtc_other", "/live/rtc_private?call_id=rtc_other"]
)
async def test_invalid_or_duplicate_call_id_denied_before_verification(voice_harness, path):
    h = voice_harness
    await _denied(h, PREFIX + path, status=400, code="invalid_realtime_call_id")
    assert not h.verified and not h.connections


async def test_native_denial_is_sanitized_and_releases_exact_owner_once(voice_harness, monkeypatch):
    h = voice_harness

    async def rejected(*_args, **_kwargs):
        raise ProxyResponseError(404, openai_error("raw_private_code", "raw_private_token_and_body"))

    monkeypatch.setattr(websocket_transport, "_connect_upstream_websocket", rejected)
    response = await _denied(h, status=404, code="desktop_voice_unavailable")
    assert "raw_private" not in response.text
    assert len(h.releases) == 1


async def test_subprotocol_mismatch_denies_before_accept_and_closes_peer(voice_harness, monkeypatch):
    h = voice_harness
    peer = _EchoPeer(selected_subprotocol="unoffered")

    async def connected(*_args, **_kwargs):
        return peer

    monkeypatch.setattr(websocket_transport, "_connect_upstream_websocket", connected)
    await _denied(h, status=502, code="upstream_websocket_subprotocol_mismatch")
    assert len(peer.close_calls) == 1 and len(h.releases) == 1


async def test_exact_owner_stream_capacity_is_enforced_and_recovered(voice_harness, monkeypatch):
    h = voice_harness
    monkeypatch.setattr(balancer_module, "effective_account_concurrency_caps", lambda: AccountConcurrencyCaps(1, 1))
    async with off_loop_test_client(h.app) as client:
        with client.websocket_connect(PREFIX + "/live/rtc_first", headers=h.headers):
            with pytest.raises(WebSocketDenialResponse) as error:
                with client.websocket_connect(PREFIX + "/live/rtc_second", headers=h.headers):
                    pytest.fail("second concurrent exact-owner stream must be denied")
            assert error.value.status_code == 429
            assert error.value.json()["error"]["code"] == "desktop_voice_capacity_exceeded"
        with client.websocket_connect(PREFIX + "/live/rtc_third", headers=h.headers):
            pass
    assert len(h.connections) == 2 and len(h.releases) == 2


async def test_legacy_live_missing_binding_is_still_denied(voice_harness):
    h = voice_harness
    await _denied(h, "/backend-api/codex/rtc_private", status=404)
    assert not h.verified and not h.connections


async def test_creation_cancellation_waits_for_lease_release_once(voice_harness, monkeypatch):
    h = voice_harness
    connector_started = asyncio.Event()
    release_started = asyncio.Event()
    allow_release = asyncio.Event()
    release_finished = asyncio.Event()
    original_release = LoadBalancer.release_account_lease

    async def wait_forever(**_kwargs):
        connector_started.set()
        await asyncio.Event().wait()

    async def delayed_release(self, lease):
        release_started.set()
        await allow_release.wait()
        await original_release(self, lease)
        release_finished.set()

    monkeypatch.setattr(voice_service, "create_desktop_voice_call", wait_forever)
    monkeypatch.setattr(LoadBalancer, "release_account_lease", delayed_release)
    task = asyncio.create_task(h.client.post(PREFIX + "/realtime/calls", headers=h.headers, content=b"offer"))
    try:
        await asyncio.wait_for(connector_started.wait(), 2)
        task.cancel()
        await asyncio.wait_for(release_started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not release_finished.is_set()
        allow_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert release_finished.is_set()
        assert len(h.releases) == 1
        assert await get_proxy_service_for_app(h.app)._load_balancer.account_pressure_snapshot(OWNER_ID) == (0, 0, 0.0)
    finally:
        allow_release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_creation_invalid_location_is_sanitized_and_releases_owner(voice_harness, monkeypatch):
    h = voice_harness

    async def invalid_location(**_kwargs):
        return CodexControlResponse(201, b"private-SDP", {"Location": "/unrecognized/private-call"})

    monkeypatch.setattr(voice_service, "create_desktop_voice_call", invalid_location)
    response = await h.client.post(PREFIX + "/realtime/calls", headers=h.headers, content=b"offer")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "desktop_voice_invalid_call_response"
    assert "private" not in response.text
    assert len(h.releases) == 1


async def test_creation_body_bound_precedes_caller_verification(voice_harness, monkeypatch):
    import app.modules.proxy.api as api_module

    h = voice_harness
    monkeypatch.setattr(api_module, "MAX_SSE_EVENT_BYTES", 4)
    response = await h.client.post(PREFIX + "/realtime/calls", headers=h.headers, content=b"oversized")
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "desktop_voice_request_too_large"
    assert not h.created and not h.verified and not h.releases
