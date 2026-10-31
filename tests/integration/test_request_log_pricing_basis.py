from __future__ import annotations

import pytest
from alembic import command
from anyio import to_thread
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.usage import pricing_catalog
from app.core.usage.pricing import ModelPrice
from app.core.usage.pricing_basis import RequestPricingBasis
from app.db.migrate import _build_alembic_config, check_schema_drift, run_upgrade
from app.db.models import RequestLog
from app.db.session import SessionLocal
from app.modules.request_logs.repository import RequestLogsRepository

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("tier", ["default", "priority", "flex", "ultrafast"])
@pytest.mark.parametrize("input_tokens", [1000, 3000])
async def test_request_details_keep_captured_rates_after_catalog_replacement(
    async_client, monkeypatch, tier, input_tokens
):
    price = ModelPrice(
        2,
        8,
        cached_input_per_1m=0.2,
        priority_multiplier=2,
        flex_input_per_1m=1,
        flex_output_per_1m=4,
        flex_cached_input_per_1m=0.1,
        ultrafast_input_per_1m=6,
        ultrafast_output_per_1m=24,
        ultrafast_cached_input_per_1m=0.6,
        long_context_threshold_tokens=2000,
        long_context_input_per_1m=4,
        long_context_output_per_1m=12,
        long_context_cached_input_per_1m=0.4,
        cache_write_input_per_1m=3,
    )
    monkeypatch.setattr(pricing_catalog, "_prices", {"snapshot-model": price})
    async with SessionLocal() as session:
        log = await RequestLogsRepository(session).add_log(
            account_id=None,
            request_id="captured-prices",
            model="snapshot-model",
            status="success",
            latency_ms=100,
            error_code=None,
            service_tier=tier,
            input_tokens=input_tokens,
            output_tokens=100,
            cached_input_tokens=200,
            cache_write_input_tokens=50,
        )
        assert log.pricing_basis_json is not None
        basis = RequestPricingBasis.model_validate_json(log.pricing_basis_json)
        saved_cost = log.cost_usd
    # Both a changed price and a removed model must leave historical detail intact.
    monkeypatch.setattr(pricing_catalog, "_prices", {})
    response = await async_client.get("/api/request-logs?search=captured-prices")
    assert response.status_code == 200
    row = response.json()["requests"][0]
    assert row["costUsd"] == saved_cost
    assert row["pricingBasis"] == basis.model_dump(by_alias=True)
    parts = row["costBreakdown"]
    assert parts["inputUsd"] == pytest.approx(
        ((input_tokens - 250) * basis.input_per_1m + 50 * basis.cache_write_input_per_1m) / 1_000_000
    )
    assert parts["cachedInputUsd"] == pytest.approx(200 * basis.cached_input_per_1m / 1_000_000)
    assert parts["outputUsd"] == pytest.approx(100 * basis.output_per_1m / 1_000_000)
    assert parts["totalUsd"] == pytest.approx(parts["inputUsd"] + parts["cachedInputUsd"] + parts["outputUsd"])


@pytest.mark.parametrize("provider", [False, True])
async def test_legacy_and_provider_totals_have_no_fabricated_pricing_basis(async_client, provider):
    async with SessionLocal() as session:
        if provider:
            await RequestLogsRepository(session).add_log(
                account_id=None,
                request_id="legacy-basis",
                model="gpt-5.1",
                status="success",
                latency_ms=100,
                error_code=None,
                input_tokens=100,
                output_tokens=10,
                cached_input_tokens=0,
                cost_usd=0.123,
                model_source_id="fixture-provider",
            )
        else:
            session.add(RequestLog(request_id="legacy-basis", model="gpt-5.1", status="success", cost_usd=0.123))
            await session.commit()
    response = await async_client.get("/api/request-logs?search=legacy-basis")
    assert response.status_code == 200
    row = response.json()["requests"][0]
    assert row["pricingBasis"] is None
    assert row["costUsd"] == 0.123


async def test_pricing_basis_migration_preserves_totals_and_roundtrips(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'pricing.sqlite'}"
    parent = "20260930_000000_add_pro_legacy_allowance"
    config = _build_alembic_config(url)
    await to_thread.run_sync(lambda: run_upgrade(url, parent, bootstrap_legacy=False))
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO request_logs (request_id, model, status, cost_usd) "
                    "VALUES ('historical', 'fixture-model', 'success', 0.123)"
                )
            )
        await to_thread.run_sync(lambda: run_upgrade(url, "head", bootstrap_legacy=False))
        assert await to_thread.run_sync(lambda: check_schema_drift(url)) == ()
        async with engine.connect() as connection:
            row = (await connection.execute(text("SELECT cost_usd, pricing_basis_json FROM request_logs"))).one()
            assert row == (0.123, None)
        await to_thread.run_sync(lambda: command.downgrade(config, parent))
        await to_thread.run_sync(lambda: run_upgrade(url, "head", bootstrap_legacy=False))
        assert await to_thread.run_sync(lambda: check_schema_drift(url)) == ()
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT cost_usd, pricing_basis_json FROM request_logs"))).one() == (
                0.123,
                None,
            )
    finally:
        await engine.dispose()
