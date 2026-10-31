import json
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

import app.core.openai.model_registry as registry_module
import app.modules.proxy.service as proxy_module
from app.core.openai.model_registry import ModelRegistry
from app.db.models import Account
from app.db.session import SessionLocal
from app.modules.proxy._service.support import _http_bridge_session_supports_service_tier
from app.modules.settings.repository import SettingsRepository
from tests.integration.test_proxy_sticky_sessions import _import_account, _set_routing_settings, _SettingsCache
from tests.integration.test_proxy_websocket_responses import (
    _completed_first_turn_upstream_batch,
    _SequencedUpstreamWebSocket,
    _websocket_settings,
)
from tests.integration.test_websocket_socket_reuse import (
    _DELTA,
    _FIRST,
    _PARENT,
    _complete,
    _create,
    _RetainedSocketFixture,
)
from tests.unit.test_model_registry import _model

pytestmark = pytest.mark.integration


async def install_catalog(monkeypatch, ids):
    model = _model("gpt-6.1-sol")
    fast = replace(model, raw={"service_tiers": [{"id": "ultrafast"}]})
    registry = ModelRegistry()
    await registry.update(
        {"promax": [fast]},
        per_account_results={account: ("promax", [model if index == 0 else fast]) for index, account in enumerate(ids)},
        active_account_plans={account: "promax" for account in ids},
    )
    monkeypatch.setattr(registry_module, "_model_registry", registry)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
async def test_ultrafast_routes_all_promax_accounts_without_rewriting_tiers(async_client, monkeypatch, path):
    await _set_routing_settings(async_client, sticky_threads_enabled=True, routing_strategy="quota_first_balanced")
    ids = [await _import_account(async_client, f"promax-{i}", f"promax-{i}@example.com") for i in range(3)]
    async with SessionLocal() as session:
        await session.execute(update(Account).where(Account.id.in_(ids)).values(plan_type="promax"))
        await session.commit()
        settings = await SettingsRepository(session).get_or_create()
    settings.http_responses_session_bridge_enabled = False
    monkeypatch.setattr(proxy_module, "get_settings_cache", lambda: _SettingsCache(settings))
    await install_catalog(monkeypatch, ids)
    seen = []

    async def stream(payload, headers, access_token, account_id, **kwargs):
        assert payload.service_tier == "ultrafast"
        seen.append(account_id)
        yield 'data: {"type":"response.completed","response":{"id":"resp_tier","service_tier":"default"}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    for index in range(6):
        response = await async_client.post(
            path,
            headers={"session-id": "promax-process", "thread-id": f"promax-thread-{index}"},
            json={
                "model": "gpt-6.1-sol",
                "service_tier": "ultrafast",
                "input": [],
                "instructions": "Test",
                "stream": True,
            },
        )
        assert response.status_code == 200, response.text
        assert '"service_tier":"default"' in response.text
    assert Counter(seen) == {f"promax-{index}": 2 for index in range(3)}


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
def test_ultrafast_omission_retains_socket_owner_and_delta(app_instance, monkeypatch, path):
    upstream = _SequencedUpstreamWebSocket(
        [],
        deferred_message_batches=[
            _completed_first_turn_upstream_batch(_PARENT),
            _completed_first_turn_upstream_batch("resp_ultrafast_next"),
        ],
    )
    fixture = _RetainedSocketFixture(monkeypatch, [upstream])
    settings = _websocket_settings()
    settings.routing_strategy = "quota_first_balanced"
    monkeypatch.setattr(proxy_module, "get_settings_cache", lambda: _SettingsCache(settings))

    async def prepare():
        await fixture.prepare()
        fixture.account.plan_type = "promax"
        async with SessionLocal() as session:
            await session.execute(update(Account).where(Account.id == fixture.account.id).values(plan_type="promax"))
            await session.commit()
        await install_catalog(monkeypatch, [fixture.account.id, "other-promax-advertiser"])
        bridge = SimpleNamespace(account=fixture.account, catalog_omission_quota_admission=None)
        assert _http_bridge_session_supports_service_tier(
            bridge, request_model="gpt-6.1-sol", request_service_tier="ultrafast"
        )

    with TestClient(app_instance) as client:
        client.portal.call(prepare)
        with client.websocket_connect(path, headers=fixture.headers()) as websocket:
            first = {**_create([_FIRST]), "model": "gpt-6.1-sol", "service_tier": "ultrafast"}
            _complete(websocket, first, _PARENT)
            continuation = {**_create([_DELTA], parent=_PARENT), "model": "gpt-6.1-sol", "service_tier": "ultrafast"}
            _complete(websocket, continuation, "resp_ultrafast_next")
    sent = json.loads(upstream.sent_text[-1])
    assert sent["input"] == [_DELTA]
    assert sent["previous_response_id"] == _PARENT
    assert sent["service_tier"] == "ultrafast"
    assert len(fixture.connects) == 1
