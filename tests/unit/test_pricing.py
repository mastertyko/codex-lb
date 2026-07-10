from __future__ import annotations

import pytest

from app.core.openai.models import ResponseUsage, ResponseUsageDetails
from app.core.usage.pricing import (
    DEFAULT_MODEL_ALIASES,
    DEFAULT_PRICING_MODELS,
    CostItem,
    ModelPrice,
    UsageTokens,
    calculate_cost_breakdown_from_usage,
    calculate_cost_from_usage,
    calculate_costs,
    get_pricing_for_model,
    resolve_model_alias,
)

pytestmark = pytest.mark.unit


def test_resolve_model_alias_longest_match():
    aliases = {
        "gpt-5*": "gpt-5",
        "gpt-5.1-codex*": "gpt-5.1-codex",
        "gpt-5.1-codex-max*": "gpt-5.1-codex-max",
    }
    assert resolve_model_alias("gpt-5.1-codex-max-2025", aliases) == "gpt-5.1-codex-max"


def test_get_pricing_for_model_alias():
    result = get_pricing_for_model("gpt-5.1-codex-mini-2025", DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result is not None
    model, price = result
    assert model == "gpt-5.1-codex-mini"
    assert price.output_per_1m == 2.0


def test_get_pricing_for_model_gpt_5_3_alias():
    result = get_pricing_for_model("gpt-5.3-codex-2026", DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result is not None
    model, _ = result
    assert model == "gpt-5.3-codex"


def test_get_pricing_for_model_gpt_5_3_chat_alias():
    result = get_pricing_for_model("gpt-5.3-chat-latest", DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result is not None
    model, _ = result
    assert model == "gpt-5.3-chat-latest"


def test_get_pricing_for_model_gpt_5_3_plain_alias():
    result = get_pricing_for_model("gpt-5.3-2026-01-01", DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result is not None
    model, _ = result
    assert model == "gpt-5.3"


def test_get_pricing_for_model_gpt_5_4_alias():
    result = get_pricing_for_model("gpt-5.4-2026", DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result is not None
    model, _ = result
    assert model == "gpt-5.4"


@pytest.mark.parametrize(
    ("requested_model", "canonical_model", "input_rate", "cached_rate", "output_rate"),
    [
        ("gpt-5.6", "gpt-5.6-sol", 5.0, 0.5, 30.0),
        ("gpt-5.6-max", "gpt-5.6-sol", 5.0, 0.5, 30.0),
        ("gpt-5.6-sol-fast", "gpt-5.6-sol", 5.0, 0.5, 30.0),
        ("gpt-5.6-terra-max", "gpt-5.6-terra", 2.5, 0.25, 15.0),
        ("gpt-5.6-luna-high", "gpt-5.6-luna", 1.0, 0.1, 6.0),
    ],
)
def test_get_pricing_for_model_gpt_5_6_aliases(
    requested_model: str,
    canonical_model: str,
    input_rate: float,
    cached_rate: float,
    output_rate: float,
) -> None:
    result = get_pricing_for_model(requested_model, DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)

    assert result is not None
    model, price = result
    assert model == canonical_model
    assert price.input_per_1m == input_rate
    assert price.cached_input_per_1m == cached_rate
    assert price.output_per_1m == output_rate
    assert price.cache_write_input_multiplier == 1.25


def test_get_pricing_for_model_gpt_5_4_mini_alias():
    result = get_pricing_for_model("gpt-5.4-mini-2026-03-17", DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result is not None
    model, price = result
    assert model == "gpt-5.4-mini"
    assert price.input_per_1m == 0.75
    assert price.cached_input_per_1m == 0.075
    assert price.output_per_1m == 4.5


def test_get_pricing_for_model_gpt_5_4_nano_alias():
    result = get_pricing_for_model("gpt-5.4-nano-2026-03-17", DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result is not None
    model, price = result
    assert model == "gpt-5.4-nano"
    assert price.input_per_1m == 0.20
    assert price.cached_input_per_1m == 0.02
    assert price.output_per_1m == 1.25


def test_get_pricing_for_model_gpt_5_2_codex_alias():
    result = get_pricing_for_model("gpt-5.2-codex-2026-03-17", DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result is not None
    model, _ = result
    assert model == "gpt-5.2-codex"


def test_get_pricing_for_model_gpt_5_2_chat_latest_alias():
    result = get_pricing_for_model("gpt-5.2-chat-latest", DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result is not None
    model, _ = result
    assert model == "gpt-5.2-chat-latest"


def test_calculate_cost_from_usage_cached_tokens():
    usage = ResponseUsage(
        input_tokens=1000,
        output_tokens=500,
        input_tokens_details=ResponseUsageDetails(cached_tokens=200),
    )
    price = ModelPrice(input_per_1m=2.0, cached_input_per_1m=0.5, output_per_1m=4.0)
    cost = calculate_cost_from_usage(usage, price)
    expected = (800 / 1_000_000) * 2.0 + (200 / 1_000_000) * 0.5 + (500 / 1_000_000) * 4.0
    assert cost == pytest.approx(expected)


def test_calculate_cost_breakdown_from_usage_cached_tokens():
    usage = UsageTokens(
        input_tokens=1_000.0,
        output_tokens=500.0,
        cached_input_tokens=200.0,
    )
    price = ModelPrice(input_per_1m=2.0, cached_input_per_1m=0.5, output_per_1m=4.0)

    breakdown = calculate_cost_breakdown_from_usage(usage, price)

    assert breakdown is not None
    assert breakdown.input_usd == pytest.approx((800 / 1_000_000) * 2.0)
    assert breakdown.cached_input_usd == pytest.approx((200 / 1_000_000) * 0.5)
    assert breakdown.output_usd == pytest.approx((500 / 1_000_000) * 4.0)
    assert breakdown.total_usd == pytest.approx(
        ((800 / 1_000_000) * 2.0) + ((200 / 1_000_000) * 0.5) + ((500 / 1_000_000) * 4.0)
    )


def test_calculate_cost_breakdown_from_usage_clamps_cached_tokens():
    usage = UsageTokens(
        input_tokens=100.0,
        output_tokens=500.0,
        cached_input_tokens=200.0,
    )
    price = ModelPrice(input_per_1m=2.0, cached_input_per_1m=0.5, output_per_1m=4.0)

    breakdown = calculate_cost_breakdown_from_usage(usage, price)

    assert breakdown is not None
    assert breakdown.input_usd == pytest.approx(0.0)
    assert breakdown.cached_input_usd == pytest.approx((100 / 1_000_000) * 0.5)
    assert breakdown.output_usd == pytest.approx((500 / 1_000_000) * 4.0)
    assert breakdown.total_usd == pytest.approx(((100 / 1_000_000) * 0.5) + ((500 / 1_000_000) * 4.0))


def test_calculate_cost_breakdown_from_usage_priority_service_tier():
    usage = UsageTokens(
        input_tokens=1_000_000.0,
        output_tokens=1_000_000.0,
        cached_input_tokens=100_000.0,
    )
    price = ModelPrice(
        input_per_1m=2.5,
        cached_input_per_1m=0.25,
        output_per_1m=15.0,
        priority_input_per_1m=5.0,
        priority_cached_input_per_1m=0.5,
        priority_output_per_1m=30.0,
    )

    breakdown = calculate_cost_breakdown_from_usage(
        usage,
        price,
        service_tier="priority",
    )

    assert breakdown is not None
    assert breakdown.input_usd == pytest.approx(4.5)
    assert breakdown.cached_input_usd == pytest.approx(0.05)
    assert breakdown.output_usd == pytest.approx(30.0)
    assert breakdown.total_usd == pytest.approx(34.55)


def test_calculate_cost_breakdown_from_usage_precision_rounds_components_first():
    usage = UsageTokens(
        input_tokens=200_000.0,
        output_tokens=100_000.0,
        cached_input_tokens=100_000.0,
    )
    price = ModelPrice(input_per_1m=0.144, cached_input_per_1m=0.144, output_per_1m=0.144)

    breakdown = calculate_cost_breakdown_from_usage(usage, price, precision=2)

    assert breakdown is not None
    assert breakdown.input_usd == pytest.approx(0.01)
    assert breakdown.cached_input_usd == pytest.approx(0.01)
    assert breakdown.output_usd == pytest.approx(0.01)
    assert breakdown.total_usd == pytest.approx(0.03)


def test_calculate_cost_from_usage_priority_service_tier():
    usage = UsageTokens(input_tokens=1_000_000.0, output_tokens=1_000_000.0)
    price = DEFAULT_PRICING_MODELS["gpt-5.4"]

    cost = calculate_cost_from_usage(usage, price, service_tier="priority")

    assert cost == pytest.approx(35.0)


def test_calculate_cost_from_usage_flex_service_tier():
    usage = UsageTokens(input_tokens=1_000_000.0, output_tokens=1_000_000.0)
    price = DEFAULT_PRICING_MODELS["gpt-5.4-mini"]

    cost = calculate_cost_from_usage(usage, price, service_tier="flex")

    assert cost == pytest.approx(2.625)


def test_calculate_cost_from_usage_service_tier_trims_whitespace():
    usage = UsageTokens(input_tokens=1_000_000.0, output_tokens=1_000_000.0)
    priority_price = DEFAULT_PRICING_MODELS["gpt-5.4"]
    flex_price = DEFAULT_PRICING_MODELS["gpt-5.4-mini"]

    priority_cost = calculate_cost_from_usage(usage, priority_price, service_tier=" priority ")
    flex_cost = calculate_cost_from_usage(usage, flex_price, service_tier=" flex ")

    assert priority_cost == pytest.approx(35.0)
    assert flex_cost == pytest.approx(2.625)


def test_calculate_cost_from_usage_legacy_gpt_5_service_tiers() -> None:
    usage = UsageTokens(input_tokens=1_000_000.0, output_tokens=1_000_000.0)

    gpt_5_priority = calculate_cost_from_usage(usage, DEFAULT_PRICING_MODELS["gpt-5"], service_tier="priority")
    gpt_5_1_flex = calculate_cost_from_usage(usage, DEFAULT_PRICING_MODELS["gpt-5.1"], service_tier="flex")
    gpt_5_2_priority = calculate_cost_from_usage(usage, DEFAULT_PRICING_MODELS["gpt-5.2"], service_tier="priority")
    gpt_5_2_flex = calculate_cost_from_usage(usage, DEFAULT_PRICING_MODELS["gpt-5.2"], service_tier="flex")

    assert gpt_5_priority == pytest.approx(22.5)
    assert gpt_5_1_flex == pytest.approx(5.625)
    assert gpt_5_2_priority == pytest.approx(31.5)
    assert gpt_5_2_flex == pytest.approx(7.875)


def test_calculate_cost_from_usage_unsupported_tiers_fall_back_to_standard():
    usage = UsageTokens(input_tokens=1_000_000.0, output_tokens=1_000_000.0)
    codex_mini = DEFAULT_PRICING_MODELS["gpt-5.1-codex-mini"]
    gpt_5_3_chat = DEFAULT_PRICING_MODELS["gpt-5.3-chat-latest"]
    gpt_5_2_chat = DEFAULT_PRICING_MODELS["gpt-5.2-chat-latest"]

    codex_mini_priority = calculate_cost_from_usage(usage, codex_mini, service_tier="priority")
    codex_mini_flex = calculate_cost_from_usage(usage, codex_mini, service_tier="flex")
    gpt_5_3_chat_priority = calculate_cost_from_usage(usage, gpt_5_3_chat, service_tier="priority")
    gpt_5_2_chat_priority = calculate_cost_from_usage(usage, gpt_5_2_chat, service_tier="priority")
    gpt_5_2_chat_flex = calculate_cost_from_usage(usage, gpt_5_2_chat, service_tier="flex")

    assert codex_mini_priority == pytest.approx(2.25)
    assert codex_mini_flex == pytest.approx(2.25)
    assert gpt_5_3_chat_priority == pytest.approx(15.75)
    assert gpt_5_2_chat_priority == pytest.approx(15.75)
    assert gpt_5_2_chat_flex == pytest.approx(15.75)


def test_calculate_cost_from_usage_gpt_5_2_codex_priority():
    usage = UsageTokens(input_tokens=1_000_000.0, output_tokens=1_000_000.0)
    price = DEFAULT_PRICING_MODELS["gpt-5.2-codex"]

    cost = calculate_cost_from_usage(usage, price, service_tier="priority")

    assert cost == pytest.approx(31.5)


def test_calculate_cost_from_usage_gpt_5_4_pro_flex():
    usage = UsageTokens(input_tokens=200_000.0, output_tokens=1_000_000.0)
    price = DEFAULT_PRICING_MODELS["gpt-5.4-pro"]

    cost = calculate_cost_from_usage(usage, price, service_tier="flex")

    assert cost == pytest.approx(93.0)


def test_calculate_cost_from_usage_gpt_5_4_long_context():
    usage = UsageTokens(
        input_tokens=300_000.0,
        output_tokens=100_000.0,
        cached_input_tokens=50_000.0,
    )
    price = DEFAULT_PRICING_MODELS["gpt-5.4"]

    cost = calculate_cost_from_usage(usage, price)

    expected = (250_000 / 1_000_000) * 5.0 + (50_000 / 1_000_000) * 0.5 + (100_000 / 1_000_000) * 22.5
    assert cost == pytest.approx(expected)


def test_calculate_cost_from_usage_gpt_5_4_long_context_flex():
    usage = UsageTokens(
        input_tokens=300_000.0,
        output_tokens=100_000.0,
        cached_input_tokens=50_000.0,
    )
    price = DEFAULT_PRICING_MODELS["gpt-5.4"]

    cost = calculate_cost_from_usage(usage, price, service_tier="flex")

    expected = (250_000 / 1_000_000) * 2.5 + (50_000 / 1_000_000) * 0.25 + (100_000 / 1_000_000) * 11.25
    assert cost == pytest.approx(expected)


@pytest.mark.parametrize(
    ("model", "input_rate", "output_rate", "long_input_rate", "long_output_rate"),
    [
        ("gpt-5.6-sol", 5.0, 30.0, 10.0, 45.0),
        ("gpt-5.6-terra", 2.5, 15.0, 5.0, 22.5),
        ("gpt-5.6-luna", 1.0, 6.0, 2.0, 9.0),
    ],
)
def test_calculate_cost_from_usage_gpt_5_6_long_context_threshold_is_exclusive(
    model: str,
    input_rate: float,
    output_rate: float,
    long_input_rate: float,
    long_output_rate: float,
) -> None:
    price = DEFAULT_PRICING_MODELS[model]

    boundary_cost = calculate_cost_from_usage(
        UsageTokens(input_tokens=272_000.0, output_tokens=1_000.0),
        price,
    )
    long_context_cost = calculate_cost_from_usage(
        UsageTokens(input_tokens=272_001.0, output_tokens=1_000.0),
        price,
    )

    assert boundary_cost == pytest.approx((272_000 / 1_000_000) * input_rate + (1_000 / 1_000_000) * output_rate)
    assert long_context_cost == pytest.approx(
        (272_001 / 1_000_000) * long_input_rate + (1_000 / 1_000_000) * long_output_rate
    )


@pytest.mark.parametrize(
    ("model", "input_rate", "cached_rate", "cache_write_rate", "output_rate"),
    [
        ("gpt-5.6-sol", 2.5, 0.25, 3.125, 15.0),
        ("gpt-5.6-terra", 1.25, 0.125, 1.5625, 7.5),
        ("gpt-5.6-luna", 0.5, 0.05, 0.625, 3.0),
    ],
)
def test_calculate_cost_from_usage_gpt_5_6_flex_short_context(
    model: str,
    input_rate: float,
    cached_rate: float,
    cache_write_rate: float,
    output_rate: float,
) -> None:
    usage = UsageTokens(
        input_tokens=200_000.0,
        output_tokens=100_000.0,
        cached_input_tokens=50_000.0,
        cache_write_input_tokens=50_000.0,
    )

    cost = calculate_cost_from_usage(usage, DEFAULT_PRICING_MODELS[model], service_tier="flex")

    assert cost == pytest.approx(
        (100_000 / 1_000_000) * input_rate
        + (50_000 / 1_000_000) * cached_rate
        + (50_000 / 1_000_000) * cache_write_rate
        + (100_000 / 1_000_000) * output_rate
    )


@pytest.mark.parametrize(
    ("model", "input_rate", "cached_rate", "cache_write_rate", "output_rate"),
    [
        ("gpt-5.6-sol", 5.0, 0.5, 6.25, 22.5),
        ("gpt-5.6-terra", 2.5, 0.25, 3.125, 11.25),
        ("gpt-5.6-luna", 1.0, 0.1, 1.25, 4.5),
    ],
)
def test_calculate_cost_from_usage_gpt_5_6_flex_long_context(
    model: str,
    input_rate: float,
    cached_rate: float,
    cache_write_rate: float,
    output_rate: float,
) -> None:
    usage = UsageTokens(
        input_tokens=300_000.0,
        output_tokens=100_000.0,
        cached_input_tokens=50_000.0,
        cache_write_input_tokens=100_000.0,
    )

    cost = calculate_cost_from_usage(usage, DEFAULT_PRICING_MODELS[model], service_tier="flex")

    assert cost == pytest.approx(
        (150_000 / 1_000_000) * input_rate
        + (50_000 / 1_000_000) * cached_rate
        + (100_000 / 1_000_000) * cache_write_rate
        + (100_000 / 1_000_000) * output_rate
    )


@pytest.mark.parametrize(
    ("model", "input_rate", "cached_rate", "cache_write_rate", "output_rate"),
    [
        ("gpt-5.6-sol", 10.0, 1.0, 12.5, 60.0),
        ("gpt-5.6-terra", 5.0, 0.5, 6.25, 30.0),
        ("gpt-5.6-luna", 2.0, 0.2, 2.5, 12.0),
    ],
)
def test_calculate_cost_from_usage_gpt_5_6_priority_short_context(
    model: str,
    input_rate: float,
    cached_rate: float,
    cache_write_rate: float,
    output_rate: float,
) -> None:
    usage = UsageTokens(
        input_tokens=200_000.0,
        output_tokens=100_000.0,
        cached_input_tokens=50_000.0,
        cache_write_input_tokens=50_000.0,
    )

    cost = calculate_cost_from_usage(usage, DEFAULT_PRICING_MODELS[model], service_tier="priority")

    assert cost == pytest.approx(
        (100_000 / 1_000_000) * input_rate
        + (50_000 / 1_000_000) * cached_rate
        + (50_000 / 1_000_000) * cache_write_rate
        + (100_000 / 1_000_000) * output_rate
    )


@pytest.mark.parametrize(
    ("model", "input_rate", "cached_rate", "cache_write_rate", "output_rate"),
    [
        ("gpt-5.6-sol", 10.0, 1.0, 12.5, 45.0),
        ("gpt-5.6-terra", 5.0, 0.5, 6.25, 22.5),
        ("gpt-5.6-luna", 2.0, 0.2, 2.5, 9.0),
    ],
)
def test_calculate_cost_from_usage_gpt_5_6_priority_long_context_uses_published_standard_rates(
    model: str,
    input_rate: float,
    cached_rate: float,
    cache_write_rate: float,
    output_rate: float,
) -> None:
    usage = UsageTokens(
        input_tokens=300_000.0,
        output_tokens=100_000.0,
        cached_input_tokens=50_000.0,
        cache_write_input_tokens=100_000.0,
    )

    cost = calculate_cost_from_usage(usage, DEFAULT_PRICING_MODELS[model], service_tier="priority")

    assert cost == pytest.approx(
        (150_000 / 1_000_000) * input_rate
        + (50_000 / 1_000_000) * cached_rate
        + (100_000 / 1_000_000) * cache_write_rate
        + (100_000 / 1_000_000) * output_rate
    )


def test_calculate_cost_from_response_usage_prices_cache_writes_separately() -> None:
    usage = ResponseUsage(
        input_tokens=1_000,
        output_tokens=100,
        input_tokens_details=ResponseUsageDetails(cached_tokens=200, cache_write_tokens=300),
    )

    breakdown = calculate_cost_breakdown_from_usage(usage, DEFAULT_PRICING_MODELS["gpt-5.6-sol"])

    assert breakdown is not None
    ordinary_input_usd = (500 / 1_000_000) * 5.0
    cache_write_usd = (300 / 1_000_000) * (5.0 * 1.25)
    assert breakdown.input_usd == pytest.approx(ordinary_input_usd + cache_write_usd)
    assert breakdown.cached_input_usd == pytest.approx((200 / 1_000_000) * 0.5)
    assert breakdown.output_usd == pytest.approx((100 / 1_000_000) * 30.0)
    assert breakdown.total_usd == pytest.approx(
        ordinary_input_usd + cache_write_usd + (200 / 1_000_000) * 0.5 + (100 / 1_000_000) * 30.0
    )


def test_calculate_cost_from_usage_gpt_5_6_long_context_prices_cache_write_from_long_rate() -> None:
    usage = UsageTokens(
        input_tokens=300_000.0,
        output_tokens=10_000.0,
        cached_input_tokens=50_000.0,
        cache_write_input_tokens=100_000.0,
    )

    breakdown = calculate_cost_breakdown_from_usage(
        usage,
        DEFAULT_PRICING_MODELS["gpt-5.6-terra"],
    )

    assert breakdown is not None
    assert breakdown.input_usd == pytest.approx((150_000 / 1_000_000) * 5.0 + (100_000 / 1_000_000) * (5.0 * 1.25))
    assert breakdown.cached_input_usd == pytest.approx((50_000 / 1_000_000) * 0.5)
    assert breakdown.output_usd == pytest.approx((10_000 / 1_000_000) * 22.5)


def test_calculate_cost_from_usage_clamps_overlapping_cached_and_cache_write_tokens() -> None:
    usage = UsageTokens(
        input_tokens=100.0,
        output_tokens=0.0,
        cached_input_tokens=80.0,
        cache_write_input_tokens=80.0,
    )
    price = ModelPrice(
        input_per_1m=2.0,
        cached_input_per_1m=0.5,
        output_per_1m=4.0,
        cache_write_input_multiplier=1.25,
    )

    breakdown = calculate_cost_breakdown_from_usage(usage, price)

    assert breakdown is not None
    assert breakdown.input_usd == pytest.approx((20 / 1_000_000) * (2.0 * 1.25))
    assert breakdown.cached_input_usd == pytest.approx((80 / 1_000_000) * 0.5)
    assert breakdown.total_usd == pytest.approx((20 / 1_000_000) * (2.0 * 1.25) + (80 / 1_000_000) * 0.5)


def test_calculate_cost_from_usage_gpt_5_4_mini():
    usage = UsageTokens(
        input_tokens=1_000_000.0,
        output_tokens=1_000_000.0,
        cached_input_tokens=100_000.0,
    )
    price = DEFAULT_PRICING_MODELS["gpt-5.4-mini"]

    cost = calculate_cost_from_usage(usage, price)

    expected = (900_000 / 1_000_000) * 0.75 + (100_000 / 1_000_000) * 0.075 + (1_000_000 / 1_000_000) * 4.5
    assert cost == pytest.approx(expected)


def test_calculate_cost_from_usage_gpt_5_4_nano():
    usage = UsageTokens(
        input_tokens=1_000_000.0,
        output_tokens=1_000_000.0,
        cached_input_tokens=100_000.0,
    )
    price = DEFAULT_PRICING_MODELS["gpt-5.4-nano"]

    cost = calculate_cost_from_usage(usage, price)

    expected = (900_000 / 1_000_000) * 0.20 + (100_000 / 1_000_000) * 0.02 + (1_000_000 / 1_000_000) * 1.25
    assert cost == pytest.approx(expected)


def test_calculate_costs_aggregates_by_model():
    items = [
        CostItem(model="gpt-5.1", usage=UsageTokens(input_tokens=1000.0, output_tokens=1000.0)),
        CostItem(model="gpt-5.1-variant", usage=UsageTokens(input_tokens=2000.0, output_tokens=1000.0)),
    ]
    result = calculate_costs(items, DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)
    assert result.currency == "USD"
    by_model = {entry.model: entry.usd for entry in result.by_model}
    assert "gpt-5.1" in by_model
    assert by_model["gpt-5.1"] > 0


def test_calculate_costs_uses_service_tier():
    items = [
        CostItem(
            model="gpt-5.4",
            service_tier="priority",
            usage=UsageTokens(input_tokens=1_000_000.0, output_tokens=1_000_000.0),
        ),
    ]

    result = calculate_costs(items, DEFAULT_PRICING_MODELS, DEFAULT_MODEL_ALIASES)

    assert result.total_usd_7d == pytest.approx(35.0)
