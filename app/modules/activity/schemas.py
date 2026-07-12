from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.modules.shared.schemas import DashboardModel


class ActivityStateResponse(DashboardModel):
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
