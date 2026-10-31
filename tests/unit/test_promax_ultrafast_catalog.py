from dataclasses import replace

import pytest

from app.core.openai.model_registry import ModelRegistry
from tests.unit.test_model_registry import _model

pytestmark = pytest.mark.unit


async def make_registry(*, advertiser_plan="promax", tier="ultrafast"):
    model = _model("gpt-6.1-sol")
    advertised = replace(model, raw={"service_tiers": [{"id": tier}]})
    registry = ModelRegistry()
    catalogs = {
        "advertiser": (advertiser_plan, [advertised]),
        "omission": ("promax", [model]),
        "other-plan": ("pro", [model]),
        "missing-model": ("promax", [_model("gpt-6-astra")]),
    }
    await registry.update(
        {advertiser_plan: [advertised]},
        per_account_results=catalogs,
        active_account_plans={account: plan for account, (plan, _) in catalogs.items()},
    )
    return registry


@pytest.mark.asyncio
async def test_promax_ultrafast_omission_resolves_without_rewriting_catalog():
    registry = await make_registry()
    before = await registry.export_state()
    assert registry.account_ids_for_model_service_tier("gpt-6.1-sol", "ultrafast") == frozenset(
        {"advertiser", "omission"}
    )
    assert registry.account_ids_for_model_service_tier(" GPT-6.1-SOL ", "ultrafast") == frozenset(
        {"advertiser", "omission"}
    )
    assert await registry.export_state() == before
    snapshot = registry.get_snapshot()
    assert snapshot is not None
    assert snapshot.model_service_tier_accounts["gpt-6.1-sol"]["ultrafast"] == frozenset({"advertiser"})


@pytest.mark.asyncio
@pytest.mark.parametrize("advertiser_plan", ["pro", "enterprise"])
async def test_other_plan_advertiser_does_not_prove_promax_ultrafast(advertiser_plan):
    registry = await make_registry(advertiser_plan=advertiser_plan)
    assert registry.account_ids_for_model_service_tier("gpt-6.1-sol", "ultrafast") == frozenset({"advertiser"})


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["priority", "flex"])
async def test_other_tiers_remain_account_specific(tier):
    registry = await make_registry(tier=tier)
    assert registry.account_ids_for_model_service_tier("gpt-6.1-sol", tier) == frozenset({"advertiser"})
    assert registry.account_ids_for_model_service_tier("gpt-6.1-sol", "ultrafast") == frozenset()


@pytest.mark.asyncio
async def test_promax_ultrafast_resolution_survives_snapshot_roundtrip():
    registry = await make_registry()
    restored = ModelRegistry()
    await restored.import_state(await registry.export_state(), content_hash="promax-ultrafast-test")
    assert restored.account_ids_for_model_service_tier("gpt-6.1-sol", "ultrafast") == frozenset(
        {"advertiser", "omission"}
    )
