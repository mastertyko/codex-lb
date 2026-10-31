from __future__ import annotations

from collections import Counter
from datetime import timezone

import pytest

import app.modules.proxy.service as proxy_module
from app.core.utils.time import utcnow
from app.db.models import StickySessionKind
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.proxy.affinity import _codex_session_selection_key
from app.modules.proxy.sticky_repository import StickySessionsRepository
from app.modules.settings.repository import SettingsRepository
from app.modules.usage.repository import UsageRepository
from tests.integration.test_proxy_sticky_sessions import _import_account, _set_routing_settings, _SettingsCache

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_responses_route_balances_new_process_siblings_and_persists_strategy(async_client, monkeypatch):
    await _set_routing_settings(async_client, sticky_threads_enabled=True, routing_strategy="quota_first_balanced")
    async with SessionLocal() as session:
        settings = await SettingsRepository(session).get_or_create()
    settings.http_responses_session_bridge_enabled = False
    monkeypatch.setattr(proxy_module, "get_settings_cache", lambda: _SettingsCache(settings))
    accounts = [await _import_account(async_client, f"quota_{i}", f"quota{i}@example.com") for i in range(2)]
    process = "quota-one-process"
    async with SessionLocal() as session:
        await StickySessionsRepository(session).upsert(
            _codex_session_selection_key(process), accounts[0], kind=StickySessionKind.CODEX_SESSION
        )
    seen = []

    async def stream(payload, headers, access_token, account_id, **kwargs):
        seen.append(account_id)
        yield f'data: {{"type":"response.completed","response":{{"id":"resp_{len(seen)}"}}}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    for index in range(10):
        response = await async_client.post(
            "/backend-api/codex/responses",
            headers={"session-id": process, "thread-id": f"thread-{index}"},
            json={"model": "gpt-5.1", "input": [], "instructions": "Test", "stream": True},
        )
        assert response.status_code == 200, response.text
    assert Counter(seen) == {"quota_0": 5, "quota_1": 5}
    response = await async_client.get("/api/settings")
    assert response.json()["routingStrategy"] == "quota_first_balanced"


@pytest.mark.asyncio
async def test_responses_route_uses_last_subscription_fraction_before_credits(async_client, monkeypatch):
    await _set_routing_settings(async_client, sticky_threads_enabled=True, routing_strategy="quota_first_balanced")
    async with SessionLocal() as session:
        settings = await SettingsRepository(session).get_or_create()
    settings.http_responses_session_bridge_enabled = False
    monkeypatch.setattr(proxy_module, "get_settings_cache", lambda: _SettingsCache(settings))
    credit, subscription = [await _import_account(async_client, f"fund_{i}", f"fund{i}@example.com") for i in range(2)]
    deadline = int(utcnow().replace(tzinfo=timezone.utc).timestamp()) + 3600
    async with SessionLocal() as session:
        repo = UsageRepository(session)
        for account_id, used in [(credit, 100.0), (subscription, 99.9)]:
            await repo.add_entry(account_id, 10.0, window="primary", reset_at=deadline, window_minutes=300)
            await repo.add_entry(
                account_id,
                used,
                window="secondary",
                reset_at=deadline,
                window_minutes=10080,
                credits_has=account_id == credit,
                credits_balance=5.0 if account_id == credit else 0.0,
            )
    seen = []

    async def stream(payload, headers, access_token, account_id, **kwargs):
        seen.append(account_id)
        yield 'data: {"type":"response.completed","response":{"id":"resp_funding"}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    response = await async_client.post(
        "/backend-api/codex/responses",
        headers={"session-id": "funding-process", "thread-id": "funding-thread"},
        json={"model": "gpt-5.1", "input": [], "instructions": "Test", "stream": True},
    )
    assert response.status_code == 200, response.text
    assert seen == ["fund_1"]
    async with SessionLocal() as session:
        await UsageRepository(session).add_entry(
            subscription,
            100.0,
            window="secondary",
            reset_at=deadline,
            window_minutes=10080,
            credits_has=False,
            credits_balance=0.0,
        )
    service = get_proxy_service_for_app(async_client._transport.app)
    service._load_balancer._selection_inputs_cache.invalidate()
    response = await async_client.post(
        "/backend-api/codex/responses",
        headers={"session-id": "funding-process", "thread-id": "credit-thread"},
        json={"model": "gpt-5.1", "input": [], "instructions": "Test", "stream": True},
    )
    assert response.status_code == 200, response.text
    assert seen == ["fund_1", "fund_0"]
