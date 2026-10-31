from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.modules.proxy.service as proxy_module
from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, RequestLog, StickySessionKind
from app.db.session import SessionLocal
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from app.modules.proxy.account_cache import clear_account_routing_unavailable
from app.modules.proxy.sticky_repository import StickySessionsRepository
from tests.integration.test_proxy_affinity_websocket_observation import SyntheticUpstream
from tests.integration.test_proxy_sticky_sessions import _install_proxy_settings_cache

pytestmark = pytest.mark.integration


async def _seed_accounts() -> None:
    encryptor = TokenEncryptor()
    async with SessionLocal() as session:
        for account_id in ("normal", "burn"):
            session.add(
                Account(
                    id=account_id,
                    chatgpt_account_id=account_id,
                    email=f"{account_id}@example.invalid",
                    plan_type="plus",
                    access_token_encrypted=encryptor.encrypt("synthetic-access"),
                    refresh_token_encrypted=encryptor.encrypt("synthetic-refresh"),
                    id_token_encrypted=encryptor.encrypt("synthetic-id"),
                    last_refresh=utcnow(),
                    status=AccountStatus.ACTIVE,
                )
            )
        await session.commit()
    # Mirror account import's availability notification after direct DB seeding.
    for account_id in ("normal", "burn"):
        clear_account_routing_unavailable(account_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/responses", "/backend-api/codex/responses"])
async def test_policy_update_moves_soft_affinity_preserving_context_and_cache_usage(async_client, monkeypatch, path):
    await _seed_accounts()
    async with SessionLocal() as session:
        await StickySessionsRepository(session).upsert("burn-context", "normal", kind=StickySessionKind.PROMPT_CACHE)

    input_items = [
        {"role": "user", "content": [{"type": "input_text", "text": "Remember the number 42."}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "The number is 42."}]},
        {"type": "function_call", "name": "recall", "arguments": "{}", "call_id": "call_memory"},
        {"type": "function_call_output", "output": "42", "call_id": "call_memory"},
        {"role": "user", "content": [{"type": "input_text", "text": "Which number did I give you?"}]},
    ]
    sent_accounts = []
    cached_counts = [80, 0, 70]

    async def stream(payload, headers, access_token, account_id, **kwargs):
        assert payload.to_payload()["input"] == input_items
        assert payload.prompt_cache_key == "burn-context"
        assert payload.previous_response_id is None
        sent_accounts.append(account_id)
        yield proxy_module.format_sse_event(
            {
                "type": "response.completed",
                "response": {
                    "id": f"resp_burn_{len(sent_accounts)}",
                    "object": "response",
                    "status": "completed",
                    "output": [],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 1,
                        "total_tokens": 101,
                        "input_tokens_details": {"cached_tokens": cached_counts[len(sent_accounts) - 1]},
                    },
                },
            }
        )

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    for index in range(3):
        if index == 1:
            updated = await async_client.put("/api/accounts/burn/routing-policy", json={"routingPolicy": "burn_first"})
            assert updated.status_code == 200
        response = await async_client.post(
            path,
            json={"model": "gpt-5.4", "input": input_items, "prompt_cache_key": "burn-context", "stream": True},
            headers={"x-request-id": f"burn-context-{index}"},
        )
        assert response.status_code == 200
        assert "response.completed" in response.text
        assert "response.failed" not in response.text

    assert sent_accounts == ["normal", "burn", "burn"]
    async with SessionLocal() as session:
        assert (
            await StickySessionsRepository(session).get_account_id("burn-context", kind=StickySessionKind.PROMPT_CACHE)
            == "burn"
        )
        logs = list((await session.scalars(select(RequestLog).order_by(RequestLog.id))).all())
        assert [row.cached_input_tokens for row in logs] == cached_counts
        assert [row.input_tokens for row in logs] == [100, 100, 100]


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_source", ["previous_response", "turn_state", "missing_turn_state", "legacy_session"])
async def test_burn_first_cannot_move_hard_context(async_client, monkeypatch, owner_source):
    await _seed_accounts()
    updated = await async_client.put("/api/accounts/burn/routing-policy", json={"routingPolicy": "burn_first"})
    assert updated.status_code == 200
    headers = {}
    payload = {
        "model": "gpt-5.4",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Continue."}]}],
        "stream": True,
    }
    if owner_source == "previous_response":
        payload["previous_response_id"] = "resp_normal_owned"

        async def resolve_owner(self, **kwargs):
            return "normal"

        monkeypatch.setattr(proxy_module.ProxyService, "_resolve_websocket_previous_response_owner", resolve_owner)
    else:
        async with SessionLocal() as session:
            await StickySessionsRepository(session).upsert("hard-owner", "normal", kind=StickySessionKind.CODEX_SESSION)
        headers["x-codex-turn-state" if "turn_state" in owner_source else "session_id"] = "hard-owner"
        if owner_source == "turn_state":

            async def resolve_turn_owner(self, **kwargs):
                return "normal"

            monkeypatch.setattr(proxy_module.ProxyService, "_resolve_compact_turn_state_owner", resolve_turn_owner)

    sent_accounts = []

    async def stream(request, upstream_headers, access_token, account_id, **kwargs):
        sent_accounts.append(account_id)
        assert request.input == payload["input"]
        assert request.previous_response_id == payload.get("previous_response_id")
        yield (
            'data: {"type":"response.completed","response":'
            '{"id":"resp_hard_burn","status":"completed","output":[]}}\n\n'
        )

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    response = await async_client.post("/backend-api/codex/responses", json=payload, headers=headers)
    if owner_source == "missing_turn_state":
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "turn_state_owner_unavailable"
        assert not sent_accounts
        return
    assert response.status_code == 200
    assert "response.completed" in response.text
    assert sent_accounts == ["normal"]


@pytest.mark.parametrize("portable", [True, False])
def test_native_websocket_reconnect_applies_burn_first_without_losing_input(app_instance, monkeypatch, portable):
    sent_accounts = []
    sent_inputs = []

    class CapturingUpstream(SyntheticUpstream):
        async def send_text(self, text):
            payload = json.loads(text)
            sent_inputs.append(payload["input"])
            assert payload["prompt_cache_key"] == "native-burn"
            await super().send_text(text)

    async def connect(headers, access_token, account_id, **kwargs):
        sent_accounts.append(account_id)
        return CapturingUpstream()

    async def seed():
        await _seed_accounts()
        async with SessionLocal() as session:
            await StickySessionsRepository(session).upsert("native-burn", "normal", kind=StickySessionKind.PROMPT_CACHE)
            key = await ApiKeysService(ApiKeysRepository(session)).create_key(
                ApiKeyCreateData(
                    name="burn-first-test", allowed_models=None, transport_policy_override="always_websocket"
                )
            )
            return key.key

    monkeypatch.setattr(proxy_module, "connect_responses_websocket", connect)
    history = [{"role": "user", "content": [{"type": "input_text", "text": "Keep this complete history."}]}]
    if not portable:
        history.append({"type": "reasoning", "encrypted_content": "synthetic-owner-bound", "summary": []})
    with TestClient(app_instance, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.portal is not None
        key = client.portal.call(seed)
        for index in range(3):
            if index == 1:
                response = client.put("/api/accounts/burn/routing-policy", json={"routingPolicy": "burn_first"})
                assert response.status_code == 200
            with client.websocket_connect(
                "ws://localhost/backend-api/codex/responses", headers={"authorization": f"Bearer {key}"}
            ) as websocket:
                websocket.send_json(
                    {"type": "response.create", "model": "gpt-5.4", "input": history, "prompt_cache_key": "native-burn"}
                )
                created = websocket.receive_json()
                assert created["type"] == "response.created", (index, sent_accounts, created)
                assert websocket.receive_json()["type"] == "response.completed"
        assert sent_accounts == (["normal", "burn", "burn"] if portable else ["normal"] * 3)
        assert sent_inputs == [history, history, history]


@pytest.mark.asyncio
async def test_burn_first_soft_rebind_waits_for_target_capacity(async_client, monkeypatch):
    from app.dependencies import get_proxy_service_for_app

    _install_proxy_settings_cache(monkeypatch, sticky_threads_enabled=False)
    await _seed_accounts()
    assert (
        await async_client.put("/api/accounts/burn/routing-policy", json={"routingPolicy": "burn_first"})
    ).is_success
    async with SessionLocal() as session:
        await StickySessionsRepository(session).upsert("burn-cap", "normal", kind=StickySessionKind.PROMPT_CACHE)
    service = get_proxy_service_for_app(async_client._transport.app)
    leases = [await service._load_balancer.acquire_account_lease("burn", kind="stream") for _ in range(8)]
    assert all(lease is not None for lease in leases)
    sent_accounts = []

    async def stream(payload, headers, access_token, account_id, **kwargs):
        sent_accounts.append(account_id)
        yield 'data: {"type":"response.completed","response":{"id":"resp_cap","status":"completed","output":[]}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    payload = {"model": "gpt-5.4", "input": [], "prompt_cache_key": "burn-cap", "stream": True}
    try:
        response = await async_client.post("/backend-api/codex/responses", json=payload)
        assert "response.completed" in response.text
        assert sent_accounts == ["normal"]
    finally:
        for lease in leases:
            await service._load_balancer.release_account_lease(lease)
    response = await async_client.post("/backend-api/codex/responses", json=payload)
    assert "response.completed" in response.text
    assert sent_accounts == ["normal", "burn"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "owned_item",
    [
        {"type": "reasoning", "encrypted_content": "synthetic-owner-bound", "summary": []},
        {"type": "function_call_output", "call_id": "call_missing", "output": "Requires missing call context"},
    ],
)
async def test_burn_first_keeps_soft_owner_when_input_is_not_portable(async_client, monkeypatch, owned_item):
    await _seed_accounts()
    assert (
        await async_client.put("/api/accounts/burn/routing-policy", json={"routingPolicy": "burn_first"})
    ).is_success
    async with SessionLocal() as session:
        await StickySessionsRepository(session).upsert("unsafe-burn", "normal", kind=StickySessionKind.PROMPT_CACHE)
    seen = []

    async def stream(payload, headers, access_token, account_id, **kwargs):
        seen.append(account_id)
        assert payload.input == [owned_item]
        yield 'data: {"type":"response.completed","response":{"id":"resp_unsafe","status":"completed","output":[]}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    response = await async_client.post(
        "/backend-api/codex/responses",
        json={"model": "gpt-5.4", "input": [owned_item], "prompt_cache_key": "unsafe-burn", "stream": True},
    )
    assert "response.completed" in response.text
    assert seen == ["normal"]
