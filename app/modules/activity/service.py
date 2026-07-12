from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import log1p
from typing import Final, Literal

from app.core.usage.types import RequestActivityAggregate
from app.core.utils.time import utcnow
from app.modules.request_logs.repository import RequestLogsRepository

DEFAULT_ACTIVITY_WINDOW_SECONDS: Final = 120
MIN_ACTIVITY_WINDOW_SECONDS: Final = 10
MAX_ACTIVITY_WINDOW_SECONDS: Final = 3600
FULL_ACTIVITY_REQUESTS: Final = 4.0
FULL_ACTIVITY_TOKENS: Final = 20_000.0
FULL_ACTIVITY_ERRORS: Final = 3.0
FULL_ACTIVITY_COST_USD: Final = 0.05
PRIMARY_ACTIVITY_WEIGHT: Final = 0.85
ERROR_ACTIVITY_WEIGHT: Final = 0.15


@dataclass(frozen=True, slots=True)
class ActivityState:
    activity: float
    stale: bool
    source: Literal["codex-lb"]
    source_status: Literal["ok"]
    generated_at: datetime
    since: datetime
    window_seconds: int
    request_count: int
    error_count: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cost_usd: float


class ActivityService:
    def __init__(self, repository: RequestLogsRepository) -> None:
        self._repository = repository

    async def get_state(self, window_seconds: int = DEFAULT_ACTIVITY_WINDOW_SECONDS) -> ActivityState:
        effective_window_seconds = clamp_activity_window_seconds(window_seconds)
        generated_at = utcnow()
        since = generated_at - timedelta(seconds=effective_window_seconds)
        aggregate = await self._repository.aggregate_activity_since(since)
        return ActivityState(
            activity=normalize_activity(aggregate),
            stale=False,
            source="codex-lb",
            source_status="ok",
            generated_at=generated_at,
            since=since,
            window_seconds=effective_window_seconds,
            request_count=aggregate.request_count,
            error_count=aggregate.error_count,
            input_tokens=aggregate.input_tokens,
            output_tokens=aggregate.output_tokens,
            cached_input_tokens=aggregate.cached_input_tokens,
            cost_usd=aggregate.cost_usd,
        )


def clamp_activity_window_seconds(window_seconds: int) -> int:
    return min(max(window_seconds, MIN_ACTIVITY_WINDOW_SECONDS), MAX_ACTIVITY_WINDOW_SECONDS)


def normalize_activity(aggregate: RequestActivityAggregate) -> float:
    if _is_idle(aggregate):
        return 0.0

    input_tokens = max(0, aggregate.input_tokens)
    cached_input_tokens = min(max(0, aggregate.cached_input_tokens), input_tokens)
    remaining_input_tokens = input_tokens - cached_input_tokens
    billable_weighted_tokens = remaining_input_tokens + max(0, aggregate.output_tokens) + cached_input_tokens * 0.25
    request_score = min(1.0, max(0.0, aggregate.request_count / FULL_ACTIVITY_REQUESTS))
    token_score = min(1.0, log1p(billable_weighted_tokens) / log1p(FULL_ACTIVITY_TOKENS))
    cost_score = min(1.0, max(0.0, aggregate.cost_usd / FULL_ACTIVITY_COST_USD))
    error_score = min(1.0, max(0.0, aggregate.error_count / FULL_ACTIVITY_ERRORS))
    raw_score = max(request_score, token_score, cost_score) * PRIMARY_ACTIVITY_WEIGHT
    raw_score += error_score * ERROR_ACTIVITY_WEIGHT
    return round(min(1.0, raw_score), 4)


def _is_idle(aggregate: RequestActivityAggregate) -> bool:
    return (
        aggregate.request_count == 0
        and aggregate.error_count == 0
        and aggregate.input_tokens == 0
        and aggregate.output_tokens == 0
        and aggregate.cached_input_tokens == 0
        and aggregate.cost_usd == 0.0
    )
