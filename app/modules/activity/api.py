from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.dependencies import ActivityContext, get_activity_context
from app.modules.activity.schemas import ActivityStateResponse
from app.modules.activity.service import DEFAULT_ACTIVITY_WINDOW_SECONDS

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("/state", response_model=ActivityStateResponse)
async def get_activity_state(
    window_seconds: int = Query(DEFAULT_ACTIVITY_WINDOW_SECONDS, alias="windowSeconds"),
    context: ActivityContext = Depends(get_activity_context),
) -> ActivityStateResponse:
    state = await context.service.get_state(window_seconds=window_seconds)
    return ActivityStateResponse(
        activity=state.activity,
        stale=state.stale,
        source=state.source,
        source_status=state.source_status,
        generated_at=state.generated_at,
        since=state.since,
        window_seconds=state.window_seconds,
        request_count=state.request_count,
        error_count=state.error_count,
        input_tokens=state.input_tokens,
        output_tokens=state.output_tokens,
        cached_input_tokens=state.cached_input_tokens,
        cost_usd=state.cost_usd,
    )
