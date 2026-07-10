from dataclasses import dataclass

import pytest

from app.core.usage.logs import cost_breakdown_from_log
from app.modules.proxy._service.request_log import _cost_with_cache_writes


@dataclass
class _RequestLog:
    model: str | None
    service_tier: str | None
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None
    cost_usd: float | None
    model_source_id: str | None = None
    model_source_kind: str | None = None


def test_request_log_cost_override_includes_gpt56_cache_writes() -> None:
    cost = _cost_with_cache_writes(
        model="gpt-5.6-sol",
        input_tokens=100,
        output_tokens=10,
        cached_input_tokens=20,
        cache_write_input_tokens=30,
        service_tier=None,
    )

    expected = ((50 * 5.0) + (20 * 0.5) + (30 * 6.25) + (10 * 30.0)) / 1_000_000
    assert cost == pytest.approx(expected)


def test_request_log_breakdown_infers_combined_input_cost_from_persisted_gpt56_total() -> None:
    persisted_cost = ((50 * 5.0) + (20 * 0.5) + (30 * 6.25) + (10 * 30.0)) / 1_000_000
    log = _RequestLog(
        model="gpt-5.6-sol",
        service_tier=None,
        input_tokens=100,
        output_tokens=10,
        cached_input_tokens=20,
        reasoning_tokens=None,
        cost_usd=persisted_cost,
    )

    breakdown = cost_breakdown_from_log(log)

    assert breakdown.input_usd == pytest.approx(((50 * 5.0) + (30 * 6.25)) / 1_000_000)
    assert breakdown.cached_input_usd == pytest.approx((20 * 0.5) / 1_000_000)
    assert breakdown.output_usd == pytest.approx((10 * 30.0) / 1_000_000)
    assert breakdown.total_usd == pytest.approx(persisted_cost)


def test_request_log_breakdown_does_not_infer_components_above_persisted_total() -> None:
    log = _RequestLog(
        model="gpt-5.6-sol",
        service_tier=None,
        input_tokens=100,
        output_tokens=10,
        cached_input_tokens=20,
        reasoning_tokens=None,
        cost_usd=0.00005,
    )

    breakdown = cost_breakdown_from_log(log)

    assert breakdown.input_usd is None
    assert breakdown.cached_input_usd is None
    assert breakdown.output_usd is None
    assert breakdown.total_usd == pytest.approx(0.00005)


def test_request_log_breakdown_does_not_infer_native_prices_for_model_source_rows() -> None:
    persisted_cost = ((50 * 5.0) + (20 * 0.5) + (30 * 6.25) + (10 * 30.0)) / 1_000_000
    log = _RequestLog(
        model="gpt-5.6-sol",
        service_tier=None,
        input_tokens=100,
        output_tokens=10,
        cached_input_tokens=20,
        reasoning_tokens=None,
        cost_usd=persisted_cost,
        model_source_id="source-openai-compatible",
        model_source_kind="openai_compatible",
    )

    breakdown = cost_breakdown_from_log(log)

    assert breakdown.input_usd is None
    assert breakdown.cached_input_usd is None
    assert breakdown.output_usd is None
    assert breakdown.total_usd == pytest.approx(persisted_cost)
