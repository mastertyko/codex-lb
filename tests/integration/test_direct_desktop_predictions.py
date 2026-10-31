from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.core.auth import desktop_oauth as auth
from app.core.auth.desktop_diagnostics import LOGGER_NAME
from app.core.auth.desktop_identity import DesktopIdentityAuthError, parse_desktop_identity_principal
from app.core.clients.proxy_websocket import UpstreamWebSocketMessage
from app.core.config.settings import DesktopOAuthGrant, get_settings
from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, ApiKey, ApiKeyUsageReservation
from app.db.session import SessionLocal
from app.modules.proxy import api as proxy_api
from app.modules.proxy import desktop_predictions as predictions
from app.modules.proxy import service as proxy_service
from app.modules.proxy._service.streaming.helpers import (
    _resolve_upstream_route_for_account as resolve_real_upstream_route,
)
from app.modules.proxy.service import ProxyService
from tests.integration.off_loop_test_client import off_loop_test_client

pytestmark = pytest.mark.integration

USER = "voice-user"
WORKSPACE = "voice-workspace"
_REAL_POOL_WEBSOCKET = ProxyService.proxy_responses_websocket


def token(*, user=USER, workspace=WORKSPACE, expires=None):
    payload = {
        "exp": expires or time.time() + 3600,
        "https://api.openai.com/auth": {
            "chatgpt_user_id": user,
            "chatgpt_account_id": workspace,
        },
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{encoded}.signature"


async def _add_account(account_id="voice-owner", *, user_id=USER, workspace_id=WORKSPACE, status=AccountStatus.PAUSED):
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
                access_token_encrypted=encryptor.encrypt(token(user=user_id, workspace=workspace_id)),
                refresh_token_encrypted=encryptor.encrypt("stored-refresh-secret"),
                id_token_encrypted=encryptor.encrypt("stored-id-secret"),
            )
        )
        await session.commit()


def body(*, prediction=True, **extra):
    source = "composer_predictions" if prediction else "user"
    return {
        "type": "response.create",
        "model": "gpt-6.1-sol",
        "instructions": "",
        "input": [],
        "client_metadata": {
            "x-codex-turn-metadata": json.dumps(
                {
                    "thread_source": source,
                    "turn_trigger": source,
                }
            )
        },
        **extra,
    }


class Peer:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.hang = False
        self.drip = False
        self.close_hang = False

    async def send_text(self, text):
        self.sent.append(json.loads(text))
        if not self.hang:
            await self.messages.put(
                UpstreamWebSocketMessage(
                    kind="text",
                    text=json.dumps(
                        {
                            "type": "response.completed",
                            "response": {
                                "id": f"caller-{len(self.sent)}",
                                "usage": {"input_tokens": 1, "output_tokens": 2},
                            },
                        }
                    ),
                )
            )

    async def receive(self):
        if self.drip:
            await asyncio.sleep(0.015)
            return UpstreamWebSocketMessage(kind="text", text='{"type":"response.output_text.delta","delta":"x"}')
        return await self.messages.get()

    async def close(self, code=1000, reason=""):
        self.closed = True
        if self.close_hang:
            await asyncio.Event().wait()

    def response_header(self, name):
        return None


@dataclass
class Harness:
    app: object
    client: object
    key_id: str
    headers: dict[str, str]
    verified: list = field(default_factory=list)
    connections: list = field(default_factory=list)
    pools: list = field(default_factory=list)
    peers: list = field(default_factory=list)
    reject: bool = False
    drip: bool = False
    close_hang: bool = False


@pytest_asyncio.fixture
async def harness(app_instance, async_client, monkeypatch):
    await _add_account(user_id=USER, workspace_id=WORKSPACE)
    result = await async_client.post(
        "/api/api-keys/",
        json={"name": "native-desktop", "allowedModels": ["gpt-6.1-sol"], "weeklyTokenLimit": 10000000},
    )
    assert result.status_code == 200, result.text
    key_id = result.json()["id"]
    grant = DesktopOAuthGrant(user_id=USER, workspace_id=WORKSPACE, api_key_id=key_id)
    monkeypatch.setattr(get_settings(), "desktop_oauth_grants", [grant])
    state = Harness(
        app_instance,
        async_client,
        key_id,
        {
            "Authorization": f"Bearer {token()}",
            "ChatGPT-Account-Id": WORKSPACE,
            "Cookie": "private-cookie",
            "X-OAI-Attestation": "private-attestation",
        },
    )

    async def verified(credentials):
        state.verified.append(credentials)
        if state.reject:
            raise DesktopIdentityAuthError()
        return parse_desktop_identity_principal(credentials.access_token, credentials.chatgpt_account_id)

    async def route(self, account, *, operation):
        assert operation == "desktop_prediction"
        return None

    async def connect(headers, access_token, account_id, **kwargs):
        peer = Peer()
        peer.drip = state.drip
        peer.close_hang = state.close_hang
        state.connections.append((headers, access_token, account_id, kwargs))
        state.peers.append(peer)
        return peer

    async def stream(payload, headers, access_token, account_id, **kwargs):
        state.connections.append((headers, access_token, account_id, kwargs))
        yield (
            'data: {"type":"response.completed","response":{"id":"caller-http",'
            '"usage":{"input_tokens":1,"output_tokens":2}}}\n\n'
        )

    async def pool(self, websocket, headers, **kwargs):
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            state.pools.append((headers, json.loads(message["text"]), kwargs["api_key"].id))
            await websocket.send_json({"type": "response.completed", "response": {"id": "pool"}})

    monkeypatch.setattr(auth, "verify_desktop_identity_principal", verified)
    monkeypatch.setattr(ProxyService, "_resolve_upstream_route_for_account", route)
    monkeypatch.setattr(ProxyService, "proxy_responses_websocket", pool)
    monkeypatch.setattr(predictions, "connect_responses_websocket", connect)
    monkeypatch.setattr(predictions, "stream_prediction", stream)
    return state


@pytest.mark.parametrize("transport", ["http", "websocket"])
async def test_prediction_routes_survive_production_repository_teardown(harness, monkeypatch, transport):
    # Keep the production repository factory, rollback/close, and route resolver.
    # The standard harness only replaces the network and bearer-verification I/O.
    monkeypatch.setattr(ProxyService, "_resolve_upstream_route_for_account", resolve_real_upstream_route)
    if transport == "http":
        response = await harness.client.post("/backend-api/codex/responses", headers=harness.headers, json=body())
        assert response.status_code == 200
        assert "response.completed" in response.text
    else:
        async with off_loop_test_client(harness.app) as client:
            with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
                socket.send_json(body())
                assert socket.receive_json()["type"] == "response.completed"

    assert len(harness.connections) == 1
    assert harness.connections[0][1] == harness.headers["Authorization"][7:]
    assert harness.connections[0][2] == WORKSPACE
    async with SessionLocal() as session:
        owner = await session.get(Account, "voice-owner")
        assert owner is not None and owner.status == AccountStatus.PAUSED
        reservations = (await session.execute(select(ApiKeyUsageReservation))).scalars().all()
        assert reservations and all(row.status == "finalized" for row in reservations)


def _diagnostic_events(caplog):
    return [json.loads(record.message) for record in caplog.records if record.name == LOGGER_NAME]


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("denied", [False, True])
async def test_route_diagnostics_cover_success_and_denial_without_content(
    harness, monkeypatch, caplog, transport, denied
):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    monkeypatch.setattr(ProxyService, "_resolve_upstream_route_for_account", resolve_real_upstream_route)
    payload = body(generate=True, input=[{"role": "user", "content": "private-prompt-body"}])
    if denied:
        payload["previous_response_id"] = "private-response-id"
    if transport == "http":
        response = await harness.client.post("/backend-api/codex/responses", headers=harness.headers, json=payload)
        assert response.status_code == (400 if denied else 200)
    else:
        async with off_loop_test_client(harness.app) as client:
            with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
                socket.send_json(payload)
                assert socket.receive_json()["type"] == ("error" if denied else "response.completed")
    events = _diagnostic_events(caplog)
    stages = {event["event"] for event in events}
    assert {"received", "auth_allowed", "frame", "classified", "closed"} <= stages
    assert any(event["lane"] == "caller" and event["source"] == "composer_predictions" for event in events)
    if denied:
        assert any(event["event"] == "denied" and event["reason"] == "unknown_continuity" for event in events)
        assert "upstream_start" not in stages
    else:
        assert {"owner_validated", "owner_ready", "policy_allowed", "upstream_start", "completed"} <= stages
    serialized = json.dumps(events)
    for secret in (
        "private-prompt-body",
        "private-response-id",
        "private-cookie",
        "private-attestation",
        harness.headers["Authorization"][7:],
        WORKSPACE,
        USER,
        harness.key_id,
    ):
        assert secret not in serialized


async def test_websocket_diagnostics_classify_each_create_frame(harness, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            for generate in (False, True):
                socket.send_json(body(generate=generate))
                assert socket.receive_json()["type"] == "response.completed"
    frames = [event for event in _diagnostic_events(caplog) if event["event"] == "frame"]
    assert [(event["frame_number"], event["generate"]) for event in frames] == [(1, False), (2, True)]
    completed = [event for event in _diagnostic_events(caplog) if event["event"] == "completed"]
    assert len(completed) == 2
    assert all(event["lane"] == "caller" for event in completed)


async def test_native_diagnostics_record_auth_denial_without_credentials(harness, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    harness.reject = True
    response = await harness.client.post("/backend-api/codex/responses", headers=harness.headers, json=body())
    assert response.status_code == 401
    events = _diagnostic_events(caplog)
    assert any(event["event"] == "auth_denied" for event in events)
    assert not any(event["event"] == "upstream_start" for event in events)
    assert harness.headers["Authorization"][7:] not in json.dumps(events)


@pytest.mark.parametrize(
    ("path", "reason"),
    [("/backend-api/codex/models", "models"), ("/backend-api/codex/unsupported", "unsupported_route")],
)
async def test_native_diagnostics_classify_route_without_logging_path(harness, caplog, path, reason):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    await harness.client.get(path, headers=harness.headers)
    events = _diagnostic_events(caplog)
    assert any(event["event"] == "request_route" and event["reason"] == reason for event in events)
    assert all(event["method"] == "GET" for event in events)
    assert path not in json.dumps(events)


@pytest.mark.parametrize("transport", ["http", "websocket"])
async def test_diagnostics_record_upstream_failure_without_error_body(harness, monkeypatch, caplog, transport):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    async def failed_stream(*args, **kwargs):
        raise RuntimeError("private-upstream-error-body")
        yield "unreachable"

    async def failed_connection(*args, **kwargs):
        raise RuntimeError("private-upstream-error-body")

    monkeypatch.setattr(predictions, "stream_prediction", failed_stream)
    monkeypatch.setattr(predictions, "connect_responses_websocket", failed_connection)
    if transport == "http":
        response = await harness.client.post("/backend-api/codex/responses", headers=harness.headers, json=body())
        assert "desktop_prediction_failed" in response.text
    else:
        async with off_loop_test_client(harness.app) as client:
            with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
                socket.send_json(body())
                assert socket.receive_json()["type"] == "error"
    events = _diagnostic_events(caplog)
    assert any(event["event"] == "failed" and event["lane"] == "caller" for event in events)
    assert "private-upstream-error-body" not in json.dumps(events)


async def test_websocket_diagnostics_record_active_cancellation(harness, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    sent = threading.Event()

    async def no_response(self, text):
        sent.set()

    monkeypatch.setattr(Peer, "send_text", no_response)
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(body())
            assert sent.wait(2)
    events = _diagnostic_events(caplog)
    assert any(event["event"] == "cancelled" and event["lane"] == "caller" for event in events)
    assert not any(event["event"] == "completed" for event in events)
    assert harness.peers[0].closed


async def test_completed_prediction_disconnect_is_not_a_failure(harness, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(body())
            assert socket.receive_json()["type"] == "response.completed"
    events = _diagnostic_events(caplog)
    assert any(event["event"] == "completed" for event in events)
    assert any(event["event"] == "disconnected" for event in events)
    assert not any(event["event"] in {"failed", "denied"} for event in events)
    assert harness.peers[0].closed
    async with SessionLocal() as session:
        rows = (await session.execute(select(ApiKeyUsageReservation))).scalars().all()
        assert rows and all(row.status == "finalized" for row in rows)


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
async def test_native_prediction_prewarm_without_trigger_retains_caller_lane(harness, path):
    prewarm = body(generate=False)
    prewarm["client_metadata"]["x-codex-turn-metadata"] = json.dumps({"thread_source": "composer_predictions"})
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect(path, headers=harness.headers) as socket:
            socket.send_json(prewarm)
            assert socket.receive_json()["response"]["id"] == "caller-1"
            socket.send_json(body(generate=True, previous_response_id="caller-1"))
            assert socket.receive_json()["response"]["id"] == "caller-2"
    assert len(harness.connections) == 1
    assert not harness.pools


@pytest.mark.parametrize(
    "generate,trigger,explicit_trigger",
    [(True, None, False), (None, None, False), (False, "user", True), (False, None, True)],
)
async def test_native_prediction_ambiguous_generation_still_denied(harness, generate, trigger, explicit_trigger):
    payload = body(generate=generate)
    metadata = {"thread_source": "composer_predictions"}
    if explicit_trigger:
        metadata["turn_trigger"] = trigger
    payload["client_metadata"]["x-codex-turn-metadata"] = json.dumps(metadata)
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(payload)
            assert socket.receive_json()["type"] == "error"
    assert not harness.connections and not harness.pools


async def test_native_pool_accepts_history_above_prediction_local_limit(harness):
    payload = body(prediction=False, input=[{"role": "user", "content": "x" * (17 * 1024 * 1024)}])
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(payload)
            assert socket.receive_json()["type"] == "response.completed"
            socket.send_json(payload)
            assert socket.receive_json()["type"] == "response.completed"
    assert len(harness.pools) == 2
    assert not harness.connections


async def test_native_pool_still_rejects_oversized_ingress(harness, monkeypatch):
    monkeypatch.setattr(predictions, "MAX_DECOMPRESSED_RESPONSES_BODY_BYTES", 1024)
    payload = body(prediction=False, input=[{"role": "user", "content": "x" * 2048}])
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(payload)
            assert socket.receive_json()["type"] == "error"
    assert not harness.connections and not harness.pools


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/backend-api/codex/v1/responses", "/v1/responses"])
async def test_http_prediction_uses_same_caller_and_policy(harness, path):
    response = await harness.client.post(path, headers=harness.headers, json=body())
    assert response.status_code == 200, response.text
    assert "response.completed" in response.text
    headers, bearer, workspace, kwargs = harness.connections[0]
    assert bearer == harness.headers["Authorization"][7:]
    assert workspace == WORKSPACE
    assert kwargs["timeout_seconds"] > 0
    assert not {"authorization", "cookie", "chatgpt-account-id", "x-codex-lb-key"} & set(headers)
    assert len(harness.verified) == 2
    async with SessionLocal() as session:
        reservations = (await session.execute(select(ApiKeyUsageReservation))).scalars().all()
        assert reservations and all(row.status == "finalized" for row in reservations)
        owner = await session.get(Account, "voice-owner")
        assert owner is not None and owner.status == AccountStatus.PAUSED


@pytest.mark.parametrize("reason", ["no_grant", "forged", "expired", "workspace", "inactive_key", "unknown_user"])
async def test_native_denials_precede_upstream(harness, monkeypatch, reason):
    headers = dict(harness.headers)
    if reason == "no_grant":
        monkeypatch.setattr(get_settings(), "desktop_oauth_grants", [])
    elif reason == "forged":
        harness.reject = True
    elif reason == "expired":
        headers["Authorization"] = f"Bearer {token(expires=time.time() - 10)}"
    elif reason == "workspace":
        headers["ChatGPT-Account-Id"] = "other"
    elif reason == "unknown_user":
        headers["Authorization"] = f"Bearer {token(user='other')}"
    elif reason == "inactive_key":
        async with SessionLocal() as session:
            await session.execute(update(ApiKey).where(ApiKey.id == harness.key_id).values(is_active=False))
            await session.commit()
    response = await harness.client.post("/backend-api/codex/responses", headers=headers, json=body())
    assert response.status_code == 401
    assert not harness.connections
    assert "private" not in response.text


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
async def test_websocket_prediction_continuity_and_close(harness, path):
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect(path, headers=harness.headers) as ws:
            ws.send_json(body(generate=False))
            assert ws.receive_json()["response"]["id"] == "caller-1"
            ws.send_json(body(generate=True, previous_response_id="caller-1"))
            assert ws.receive_json()["response"]["id"] == "caller-2"
    assert len(harness.connections) == 1
    assert harness.connections[0][3]["caller_owned"] is True
    assert harness.peers[0].closed
    assert len(harness.verified) == 3
    assert not harness.pools


@pytest.mark.parametrize("start_prediction", [True, False])
async def test_websocket_cannot_switch_lane(harness, start_prediction):
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as ws:
            ws.send_json(body(prediction=start_prediction))
            assert ws.receive_json()["type"] == "response.completed"
            ws.send_json(body(prediction=not start_prediction))
            if start_prediction:
                assert ws.receive_json()["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert len(harness.connections) == int(start_prediction)
    assert len(harness.pools) == int(not start_prediction)


@pytest.mark.parametrize("prediction", [True, False])
async def test_open_socket_rechecks_online_revocation(harness, prediction):
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as ws:
            ws.send_json(body(prediction=prediction))
            assert ws.receive_json()["type"] == "response.completed"
            harness.reject = True
            ws.send_json(body(prediction=prediction))
            if prediction:
                assert ws.receive_json()["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert len(harness.connections) + len(harness.pools) == 1


async def test_native_pool_retains_frames_during_slow_auth_across_receive_polls(harness, monkeypatch):
    """Exercise the production pool receive loop; reject models before external transport."""
    prepared = threading.Event()
    prepared_models = []
    verified = []
    original_prepare = ProxyService._prepare_websocket_response_create_request

    async def slow_verification(credentials):
        verified.append(credentials)
        if len(verified) > 1:
            await asyncio.sleep(0.08)
        return parse_desktop_identity_principal(credentials.access_token, credentials.chatgpt_account_id)

    async def observe_prepare(self, payload, **kwargs):
        prepared_models.append(payload["model"])
        prepared.set()
        return await original_prepare(self, payload, **kwargs)

    monkeypatch.setattr(auth, "verify_desktop_identity_principal", slow_verification)
    monkeypatch.setattr(ProxyService, "proxy_responses_websocket", _REAL_POOL_WEBSOCKET)
    monkeypatch.setattr(ProxyService, "_prepare_websocket_response_create_request", observe_prepare)
    monkeypatch.setattr(proxy_service, "_DOWNSTREAM_WEBSOCKET_RECEIVE_POLL_SECONDS", 0.02)
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            for model in ("disallowed-model-one", "disallowed-model-two"):
                prepared.clear()
                socket.send_json(body(prediction=False, model=model))
                assert prepared.wait(1), "Consumed native frame was lost during the pool receive poll"
                assert socket.receive_json()["status"] == 403
    assert prepared_models == ["disallowed-model-one", "disallowed-model-two"]
    assert len(verified) == 3  # Handshake, then exactly one verification per frame.
    assert not harness.connections


async def test_native_pool_cancels_owned_auth_task_when_connection_ends(harness, monkeypatch):
    started = threading.Event()
    cancelled = threading.Event()
    calls = []

    async def blocked_verification(credentials):
        calls.append(credentials)
        if len(calls) > 1:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return parse_desktop_identity_principal(credentials.access_token, credentials.chatgpt_account_id)

    monkeypatch.setattr(auth, "verify_desktop_identity_principal", blocked_verification)
    monkeypatch.setattr(ProxyService, "proxy_responses_websocket", _REAL_POOL_WEBSOCKET)
    monkeypatch.setattr(proxy_service, "_DOWNSTREAM_WEBSOCKET_RECEIVE_POLL_SECONDS", 0.02)
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(body(prediction=False))
            assert started.wait(1)
        assert cancelled.wait(1)
    assert len(calls) == 2
    assert not harness.connections


@pytest.mark.parametrize(
    "extra", [{"previous_response_id": "pool"}, {"input": [{"type": "input_file", "file_id": "pool-file"}]}]
)
async def test_prediction_denies_foreign_continuity_and_files(harness, extra):
    response = await harness.client.post("/backend-api/codex/responses", headers=harness.headers, json=body(**extra))
    assert response.status_code == 400
    assert not harness.connections


async def test_continuous_deltas_cannot_extend_turn_budget(harness, monkeypatch):
    harness.drip = True
    monkeypatch.setattr(get_settings(), "proxy_request_budget_seconds", 0.08)
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(body())
            events = [socket.receive_json()]
            while events[-1]["type"] != "error" and len(events) < 20:
                events.append(socket.receive_json())
            assert events[-1]["type"] == "error"
    assert harness.peers[0].closed
    async with SessionLocal() as session:
        rows = (await session.execute(select(ApiKeyUsageReservation))).scalars().all()
        assert rows and all(row.status == "released" for row in rows)


async def test_downstream_send_timeout_releases_reservation(harness, monkeypatch):
    harness.drip = True
    original = WebSocket.send_text

    async def stuck(self, data):
        if '"delta"' in data:
            await asyncio.Event().wait()
        await original(self, data)

    monkeypatch.setattr(WebSocket, "send_text", stuck)
    monkeypatch.setattr(get_settings(), "proxy_request_budget_seconds", 0.05)
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(body())
            assert socket.receive_json()["type"] == "error"
    assert harness.peers[0].closed


async def test_stuck_upstream_close_is_bounded(harness, monkeypatch):
    harness.close_hang = True
    monkeypatch.setattr(predictions, "_CLOSE_TIMEOUT_SECONDS", 0.02)
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(body())
            assert socket.receive_json()["type"] == "response.completed"
    assert harness.peers[0].closed


@pytest.mark.parametrize("prediction", [True, False])
async def test_open_socket_rechecks_server_grant(harness, monkeypatch, prediction):
    async with off_loop_test_client(harness.app) as client:
        with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
            socket.send_json(body(prediction=prediction))
            assert socket.receive_json()["type"] == "response.completed"
            monkeypatch.setattr(get_settings(), "desktop_oauth_grants", [])
            socket.send_json(body(prediction=prediction))
            if prediction:
                assert socket.receive_json()["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
    assert len(harness.connections) + len(harness.pools) == 1


async def test_native_http_ordinary_uses_pool_without_caller_headers(harness, monkeypatch):
    from starlette.responses import JSONResponse

    async def pooled(request, payload, context, api_key, **kwargs):
        harness.pools.append((dict(request.headers), payload, api_key.id))
        return JSONResponse({"id": "pool-http"})

    monkeypatch.setattr(proxy_api, "_stream_responses", pooled)
    response = await harness.client.post(
        "/backend-api/codex/responses", headers=harness.headers, json=body(prediction=False)
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == "pool-http"
    assert not harness.connections
    assert harness.pools[0][2] == harness.key_id
    assert not {"authorization", "cookie", "chatgpt-account-id", "x-oai-attestation"} & set(harness.pools[0][0])


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("prefix", ["/backend-api/codex", "/backend-api/codex/v1", "/v1"])
@pytest.mark.parametrize("suffix", ["/realtime/calls", "/realtime?call_id=rtc_private", "/live/rtc_private"])
async def test_native_realtime_is_not_remapped_or_dispatched(harness, monkeypatch, transport, prefix, suffix):
    async def forbidden(*args, **kwargs):
        pytest.fail("retired native realtime must fail before upstream or owner work")

    monkeypatch.setattr(auth, "verify_desktop_identity_principal", forbidden)
    monkeypatch.setattr(ProxyService, "proxy_realtime_live_websocket", forbidden)
    async with off_loop_test_client(harness.app) as client:
        path = prefix + suffix
        if transport == "http":
            response = client.post(path, headers=harness.headers)
        else:
            from starlette.testclient import WebSocketDenialResponse

            with pytest.raises(WebSocketDenialResponse) as denied:
                with client.websocket_connect(path, headers=harness.headers):
                    pytest.fail("native realtime must not connect")
            response = denied.value
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "desktop_oauth_denied"
    assert not harness.verified and not harness.connections and not harness.pools


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize(
    "state", ["active", "paused", "missing", "ambiguous", "deleted", "deactivated", "user", "workspace", "scope"]
)
async def test_prediction_exact_owner_policy_survives_voice_removal(harness, transport, state):
    if state == "ambiguous":
        await _add_account("duplicate-owner")
    async with SessionLocal() as session:
        owner = await session.get(Account, "voice-owner")
        assert owner is not None
        if state == "active":
            owner.status = AccountStatus.ACTIVE
        elif state == "missing":
            await session.delete(owner)
        elif state == "deleted":
            owner.delete_requested_at = utcnow()
        elif state == "deactivated":
            owner.status = AccountStatus.DEACTIVATED
        elif state == "user":
            owner.chatgpt_user_id = "another-user"
        elif state == "workspace":
            owner.chatgpt_account_id = "another-workspace"
        elif state == "scope":
            key = await session.get(ApiKey, harness.key_id)
            key.account_assignment_scope_enabled = True
            # An empty enabled assignment set excludes every owner.
        await session.commit()
    allowed = state in {"active", "paused"}
    if transport == "http":
        response = await harness.client.post("/backend-api/codex/responses", headers=harness.headers, json=body())
        assert response.status_code == 200
        assert ('"type":"response.completed"' in response.text) is allowed
        assert ('"code":"desktop_prediction_failed"' in response.text) is not allowed
    else:
        async with off_loop_test_client(harness.app) as client:
            with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
                socket.send_json(body())
                assert socket.receive_json()["type"] == ("response.completed" if allowed else "error")
    assert len(harness.connections) == int(allowed)
    assert not harness.pools
    async with SessionLocal() as session:
        reservations = (
            (await session.execute(select(ApiKeyUsageReservation).where(ApiKeyUsageReservation.status == "reserved")))
            .scalars()
            .all()
        )
        assert not reservations
        if allowed:
            owner = await session.get(Account, "voice-owner")
            assert owner.status == (AccountStatus.ACTIVE if state == "active" else AccountStatus.PAUSED)


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("mutation", ["identity", "status"])
async def test_prediction_rechecks_owner_after_routing_and_releases_lease(harness, monkeypatch, transport, mutation):
    from app.modules.proxy.load_balancer import LoadBalancer

    released = []
    original_release = LoadBalancer.release_account_lease

    async def release(self, lease):
        released.append(lease)
        await original_release(self, lease)

    async def route(self, account, *, operation):
        assert operation == "desktop_prediction"
        async with SessionLocal() as session:
            owner = await session.get(Account, account.id)
            if mutation == "identity":
                owner.chatgpt_user_id = "changed-user"
            else:
                owner.status = AccountStatus.DEACTIVATED
            await session.commit()
        return None

    monkeypatch.setattr(LoadBalancer, "release_account_lease", release)
    monkeypatch.setattr(ProxyService, "_resolve_upstream_route_for_account", route)
    if transport == "http":
        response = await harness.client.post("/backend-api/codex/responses", headers=harness.headers, json=body())
        assert '"code":"desktop_prediction_failed"' in response.text
    else:
        async with off_loop_test_client(harness.app) as client:
            with client.websocket_connect("/backend-api/codex/responses", headers=harness.headers) as socket:
                socket.send_json(body())
                assert socket.receive_json()["type"] == "error"
    assert not harness.connections and not harness.pools
    assert len(released) == 1 and released[0] is not None
    async with SessionLocal() as session:
        assert (
            not (
                await session.execute(select(ApiKeyUsageReservation).where(ApiKeyUsageReservation.status == "reserved"))
            )
            .scalars()
            .all()
        )
