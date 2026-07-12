from __future__ import annotations

from app.core.usage.types import RequestActivityAggregate
from app.modules.activity.service import clamp_activity_window_seconds, normalize_activity


def _aggregate(
    *,
    request_count: int = 0,
    error_count: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    cost_usd: float = 0.0,
) -> RequestActivityAggregate:
    return RequestActivityAggregate(
        request_count=request_count,
        error_count=error_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        cost_usd=cost_usd,
    )


def test_normalize_activity_reports_exact_idle_zero() -> None:
    assert normalize_activity(_aggregate()) == 0.0


def test_normalize_activity_weights_cached_tokens_and_errors() -> None:
    input_score = normalize_activity(_aggregate(input_tokens=25))
    cached_score = normalize_activity(_aggregate(input_tokens=100, cached_input_tokens=100))
    error_score = normalize_activity(_aggregate(input_tokens=25, error_count=1))

    assert cached_score == input_score
    assert error_score == round(input_score + 0.05, 4)


def test_normalize_activity_is_bounded_at_full_activity() -> None:
    activity = normalize_activity(
        _aggregate(
            request_count=100,
            error_count=100,
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cached_input_tokens=1_000_000,
            cost_usd=100.0,
        )
    )

    assert activity == 1.0


def test_clamp_activity_window_seconds_enforces_query_bounds() -> None:
    assert clamp_activity_window_seconds(-1) == 10
    assert clamp_activity_window_seconds(10) == 10
    assert clamp_activity_window_seconds(120) == 120
    assert clamp_activity_window_seconds(3600) == 3600
    assert clamp_activity_window_seconds(999_999) == 3600
