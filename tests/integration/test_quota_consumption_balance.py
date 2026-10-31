from __future__ import annotations

from datetime import timezone

import pytest
from sqlalchemy import update

import app.modules.proxy.service as proxy_module
from app.core.utils.time import utcnow
from app.db.models import Account
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.settings.repository import SettingsRepository
from app.modules.usage.repository import UsageRepository
from tests.integration.test_promax_ultrafast import install_catalog
from tests.integration.test_proxy_sticky_sessions import _import_account, _set_routing_settings, _SettingsCache

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
async def test_ultrafast_quota_catchup_and_sticky_owner_on_real_route(async_client, monkeypatch, path):
    await _set_routing_settings(async_client, sticky_threads_enabled=True, routing_strategy="quota_first_balanced")
    ids = [await _import_account(async_client, name, f"{name}@example.com") for name in ["unused", "middle", "busy"]]
    async with SessionLocal() as session:
        await session.execute(update(Account).where(Account.id.in_(ids)).values(plan_type="promax"))
        await session.commit()
        settings = await SettingsRepository(session).get_or_create()
    settings.http_responses_session_bridge_enabled = False
    monkeypatch.setattr(proxy_module, "get_settings_cache", lambda: _SettingsCache(settings))
    await install_catalog(monkeypatch, ids)
    service = get_proxy_service_for_app(async_client._transport.app)
    deadline = int(utcnow().replace(tzinfo=timezone.utc).timestamp()) + 7 * 86400

    async def quota(values):
        async with SessionLocal() as session:
            repo = UsageRepository(session)
            for account, value in zip(ids, values, strict=True):
                await repo.add_entry(account, value, window="primary", reset_at=deadline, window_minutes=10080)
        service._load_balancer._selection_inputs_cache.invalidate()

    seen = []

    async def stream(payload, headers, access_token, account_id, **kwargs):
        assert payload.service_tier == "ultrafast"
        seen.append(account_id)
        yield 'data: {"type":"response.completed","response":{"id":"resp_quota","service_tier":"default"}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)

    async def request(thread):
        response = await async_client.post(
            path,
            headers={"session-id": "same-process", "thread-id": thread},
            json={
                "model": "gpt-6.1-sol",
                "service_tier": "ultrafast",
                "prompt_cache_key": thread,
                "input": [],
                "instructions": "Test",
                "stream": True,
            },
        )
        assert response.status_code == 200, response.text
        return seen[-1]

    await quota([46, 37, 0])
    assert await request("old-busy-owner") == "busy"
    await quota([0, 37, 46])
    for index in range(3):
        assert await request(f"catchup-{index}") == "unused"
    assert await request("old-busy-owner") == "busy"
    await quota([39, 37, 46])
    assert await request("after-catchup") == "middle"
    assert await request("catchup-0") == "unused"
