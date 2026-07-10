from __future__ import annotations

import pytest

from app.core.openai.model_registry import ReasoningLevel, UpstreamModel, get_model_registry

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_dashboard_model_policy_exposes_max_but_filters_native_only_ultra(async_client) -> None:
    model = UpstreamModel(
        slug="dashboard-reasoning-policy",
        display_name="Dashboard reasoning policy",
        description="Dashboard reasoning policy test model",
        context_window=372_000,
        input_modalities=("text",),
        supported_reasoning_levels=tuple(
            ReasoningLevel(effort=effort, description=effort) for effort in ("low", "max", "ultra")
        ),
        default_reasoning_level="low",
        supports_reasoning_summaries=False,
        support_verbosity=False,
        default_verbosity=None,
        prefer_websockets=True,
        supports_parallel_tool_calls=True,
        supported_in_api=True,
        minimal_client_version=None,
        priority=0,
        available_in_plans=frozenset({"plus", "pro"}),
        raw={"shell_type": "shell_command", "visibility": "list"},
    )
    await get_model_registry().update({"plus": [model], "pro": [model]})

    dashboard_response = await async_client.get("/api/models")
    native_response = await async_client.get("/backend-api/codex/models")

    assert dashboard_response.status_code == 200
    dashboard_model = next(item for item in dashboard_response.json()["models"] if item["id"] == model.slug)
    assert dashboard_model["supportedReasoningEfforts"] == ["low", "max"]

    assert native_response.status_code == 200
    native_model = next(item for item in native_response.json()["models"] if item["slug"] == model.slug)
    assert [level["effort"] for level in native_model["supported_reasoning_levels"]] == [
        "low",
        "max",
        "ultra",
    ]
