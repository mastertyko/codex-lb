import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

import app.modules.proxy.service as proxy_module
from app.core.clients.proxy_websocket import UpstreamWebSocketMessage
from app.core.openai.models import CompactResponsePayload
from app.db.models import Account, RequestLog
from app.db.session import SessionLocal
from app.modules.api_keys.service import ApiKeysService
from app.modules.proxy.load_balancer import AccountSelection
from app.modules.settings.repository import SettingsRepository
from tests.integration.test_http_responses_bridge import _install_bridge_settings
from tests.integration.test_promax_ultrafast import install_catalog
from tests.integration.test_proxy_sticky_sessions import _import_account, _SettingsCache
from tests.integration.test_proxy_websocket_responses import (
    _REAL_WRITE_REQUEST_LOG,
    _SequencedUpstreamWebSocket,
)
from tests.integration.test_websocket_socket_reuse import _FIRST, _complete, _create, _RetainedSocketFixture

pytestmark = pytest.mark.integration
USAGE = {"input_tokens": 100000, "output_tokens": 1000, "input_tokens_details": {"cached_tokens": 90000}}


def _price_event(payload):
    return UpstreamWebSocketMessage("text", text=json.dumps(payload))


async def read_log(response_id):
    async with asyncio.timeout(5):
        while True:
            async with SessionLocal() as session:
                log = await session.scalar(
                    select(RequestLog).where(RequestLog.request_id == response_id)
                    if response_id
                    else select(RequestLog)
                )
                if log is not None:
                    session.expunge(log)
                    return log
            await asyncio.sleep(0.01)


def assert_log(log, actual, tier, cost):
    assert log.requested_service_tier == "ultrafast"
    assert log.actual_service_tier == actual
    assert log.service_tier == tier
    assert log.cost_usd == pytest.approx(cost)


async def prepare_account(async_client, monkeypatch):
    account = await _import_account(async_client, "ultra-price", "ultra@example.com")
    async with SessionLocal() as session:
        await session.execute(update(Account).where(Account.id == account).values(plan_type="promax"))
        await session.commit()
    await install_catalog(monkeypatch, [account])
    async with SessionLocal() as session:
        selected = await session.get(Account, account)
        session.expunge(selected)

    async def select_account(self, *args, **kwargs):
        return AccountSelection(account=selected, error_message=None, error_code=None)

    async def ensure_fresh(self, account, **kwargs):
        return account

    monkeypatch.setattr(proxy_module.ProxyService, "_select_account_with_budget", select_account)
    monkeypatch.setattr(proxy_module.ProxyService, "_ensure_fresh_with_budget", ensure_fresh)


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
@pytest.mark.parametrize("bridge", [False, True])
@pytest.mark.parametrize(
    "actual,tier,cost",
    [
        ("default", "ultrafast", 0.234),
        ("auto", "ultrafast", 0.234),
        ("priority", "priority", 0.078),
        ("flex", "flex", 0.0195),
    ],
)
async def test_http_accounting_preserves_raw_tier(async_client, monkeypatch, path, actual, tier, cost, bridge):
    await prepare_account(async_client, monkeypatch)
    async with SessionLocal() as session:
        settings = await SettingsRepository(session).get_or_create()
    settings.http_responses_session_bridge_enabled = False
    monkeypatch.setattr(proxy_module, "get_settings_cache", lambda: _SettingsCache(settings))

    async def stream(payload, *args, **kwargs):
        assert payload.service_tier == "ultrafast"
        yield (
            "data: "
            + json.dumps({"type": "response.created", "response": {"id": "resp_ultra_http", "service_tier": "auto"}})
            + "\n\n"
        )
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": {"id": "resp_ultra_http", "service_tier": actual, "usage": USAGE},
                }
            )
            + "\n\n"
        )

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    if bridge:
        _install_bridge_settings(monkeypatch, enabled=True)
        upstream = _SequencedUpstreamWebSocket(
            [],
            deferred_message_batches=[
                [
                    _price_event(
                        {"type": "response.created", "response": {"id": "resp_ultra_http", "service_tier": "auto"}}
                    ),
                    _price_event(
                        {
                            "type": "response.completed",
                            "response": {"id": "resp_ultra_http", "service_tier": actual, "usage": USAGE},
                        }
                    ),
                ]
            ],
        )

        async def connect(*args, **kwargs):
            return upstream

        async def no_http(*args, **kwargs):
            raise AssertionError("Bridge must use the WebSocket transport")
            yield

        monkeypatch.setattr(proxy_module, "connect_responses_websocket", connect)
        monkeypatch.setattr(proxy_module, "core_stream_responses", no_http)
    response = await async_client.post(
        path, json={"model": "gpt-6.1-sol", "service_tier": "ultrafast", "input": [], "stream": True}
    )
    assert response.status_code == 200, response.text
    assert "response.failed" not in response.text, response.text
    assert f'"service_tier": "{actual}"' in response.text or f'"service_tier":"{actual}"' in response.text
    assert_log(await read_log("resp_ultra_http"), actual, tier, cost)


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
@pytest.mark.parametrize("actual,tier,cost", [("default", "ultrafast", 0.234), ("priority", "priority", 0.078)])
def test_websocket_cost_and_key_settlement_agree(app_instance, monkeypatch, path, actual, tier, cost):
    response = {
        "id": "resp_ultra_ws",
        "object": "response",
        "status": "completed",
        "model": "gpt-6.1-sol",
        "service_tier": actual,
        "usage": USAGE,
    }
    upstream = _SequencedUpstreamWebSocket(
        [],
        deferred_message_batches=[
            [
                _price_event({"type": "response.created", "response": {"id": "resp_ultra_ws", "service_tier": "auto"}}),
                _price_event({"type": "response.completed", "response": response}),
            ]
        ],
    )
    fixture = _RetainedSocketFixture(monkeypatch, [upstream], limited=True)
    monkeypatch.setattr(proxy_module.ProxyService, "_write_request_log", _REAL_WRITE_REQUEST_LOG)
    settlements = []
    original = ApiKeysService.finalize_usage_reservation

    async def finalize(self, *args, **kwargs):
        settlements.append(kwargs)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ApiKeysService, "finalize_usage_reservation", finalize)

    async def prepare():
        await fixture.prepare()
        await install_catalog(monkeypatch, [fixture.account.id])

    with TestClient(app_instance) as client:
        client.portal.call(prepare)
        with client.websocket_connect(path, headers=fixture.headers()) as websocket:
            _complete(
                websocket, {**_create([_FIRST]), "model": "gpt-6.1-sol", "service_tier": "ultrafast"}, "resp_ultra_ws"
            )
        log = client.portal.call(read_log, "resp_ultra_ws")
    assert_log(log, actual, tier, cost)
    assert settlements and settlements[0]["service_tier"] == tier
    assert json.loads(upstream.sent_text[0])["service_tier"] == "ultrafast"


@pytest.mark.parametrize("actual,tier,cost", [("default", "ultrafast", 0.234), ("priority", "priority", 0.078)])
async def test_compaction_log_and_settlement_agree(async_client, monkeypatch, actual, tier, cost):
    await prepare_account(async_client, monkeypatch)
    settings = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert settings.status_code == 200
    key_response = await async_client.post(
        "/api/api-keys/",
        json={
            "name": "ultrafast-cost",
            "limits": [{"limitType": "total_tokens", "limitWindow": "weekly", "maxValue": 1000000}],
        },
    )
    assert key_response.status_code == 200
    token = key_response.json()["key"]

    async def compact(payload, *args, **kwargs):
        assert payload.service_tier == "ultrafast"
        return CompactResponsePayload.model_validate(
            {
                "object": "response.compaction",
                "service_tier": actual,
                "compaction_summary": {"id": "cmp_ultra", "encrypted_content": "encrypted"},
                "usage": USAGE,
            }
        )

    monkeypatch.setattr(proxy_module, "core_compact_responses", compact)
    settlements = []
    original = ApiKeysService.finalize_usage_reservation

    async def finalize(self, *args, **kwargs):
        settlements.append(kwargs)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ApiKeysService, "finalize_usage_reservation", finalize)
    response = await async_client.post(
        "/v1/responses/compact",
        headers={"authorization": f"Bearer {token}"},
        json={"model": "gpt-6.1-sol", "service_tier": "ultrafast", "instructions": "hi", "input": []},
    )
    assert response.status_code == 200, response.text
    assert response.json()["service_tier"] == actual
    log = await read_log(None)
    assert_log(log, actual, tier, cost)
    assert settlements and settlements[0]["service_tier"] == tier
