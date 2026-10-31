import pytest

from app.core.usage import pricing_catalog
from app.core.usage.pricing import (
    UsageTokens,
    calculate_cost_from_usage,
    get_pricing_for_model,
    subscription_pricing_tier,
)


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6-astra", "gpt-6.1-sol-2026-10-08"])
@pytest.mark.parametrize(
    "actual,expected",
    [
        ("auto", "ultrafast"),
        ("default", "ultrafast"),
        (None, "ultrafast"),
        ("ultrafast", "ultrafast"),
        ("priority", "priority"),
        ("flex", "flex"),
    ],
)
def test_subscription_ultrafast_retains_explicit_tiers(monkeypatch, model, actual, expected):
    monkeypatch.setattr(pricing_catalog, "_prices", None)
    assert subscription_pricing_tier(model, "ultrafast", actual) == expected


@pytest.mark.parametrize(
    "model,requested,actual,expected",
    [
        ("gpt-6-sol", "ultrafast", "default", "default"),
        ("unknown", "ultrafast", "auto", "auto"),
        ("gpt-6.1-sol", "priority", "default", "default"),
        ("gpt-6.1-sol", None, "default", "default"),
        ("gpt-6.1-sol", "auto", "default", "default"),
    ],
)
def test_unrelated_requests_keep_reported_tier(model, requested, actual, expected):
    assert subscription_pricing_tier(model, requested, actual) == expected


@pytest.mark.parametrize("model,factor", [("gpt-6.1-sol", 1), ("gpt-6-astra", 5)])
@pytest.mark.parametrize(
    "inputs,cached,writes,sol_cost",
    [
        (100000, 90000, 0, 0.234),
        (100000, 90000, 5000, 0.249),
        (272000, 250000, 0, 0.474),
        (272001, 250000, 0, 0.918024),
    ],
)
def test_offline_ultrafast_rates(monkeypatch, model, factor, inputs, cached, writes, sol_cost):
    monkeypatch.setattr(pricing_catalog, "_prices", None)
    _, price = get_pricing_for_model(model)
    # Astra cached input is 6 rather than Sol's .6 (10x), while other rates are 5x.
    expected = sol_cost * factor
    if factor == 5:
        expected += cached * (6 - 0.6 * 5) * (2 if inputs > 272000 else 1) / 1e6
    assert calculate_cost_from_usage(
        UsageTokens(inputs, 1000, cached, writes), price, service_tier="ultrafast"
    ) == pytest.approx(expected)
