"""Conservative quota moves of unsent, complete WebSocket conversation turns."""

from __future__ import annotations

import json
import logging
import math
from copy import deepcopy
from dataclasses import replace
from datetime import timezone

from app.core.balancer import select_account
from app.core.balancer.logic import quota_first_consumption
from app.core.types import JsonValue
from app.db.models import AccountStatus, StickySessionKind
from app.modules.proxy._service.response_create import _fingerprint_input_items, _upstream_response_create_max_bytes
from app.modules.proxy._service.support import _WebSocketContinuityState, _WebSocketRequestState
from app.modules.proxy._service.websocket.helpers import (
    _install_fresh_replay_body,
    _websocket_full_resend_retains_prior_output,
    _websocket_request_text_is_account_neutral_fresh_replay,
)
from app.modules.proxy.load_balancer import LoadBalancer, _build_states
from app.modules.proxy.quota_context import native_quota_context_is_complete

logger = logging.getLogger(__name__)


async def prepare_quota_rebalance(
    balancer: LoadBalancer,
    request: _WebSocketRequestState,
    *,
    account_id: str,
    continuity: _WebSocketContinuityState,
    client_input: JsonValue,
) -> str | None:
    """Install a full request only after proving both mobility and a large gap.

    The caller owns the idle-boundary and explicit turn-state checks. This
    preflight mutates no account health, leases, sticky mappings or counters.
    The ordinary connector rechecks admission before dispatch.
    """
    if (
        request.steering_parent_response_id is not None
        or request.file_required_preferred_account
        or request.source_route_excluded
        or request.require_security_work_authorized
        or request.affinity_policy.require_unambiguous_account
        or request.replay_count
        or not request.proxy_injected_previous_response_id
        or request.affinity_policy.kind != StickySessionKind.PROMPT_CACHE
    ):
        return None
    fresh_text = _complete_context_text(request, continuity, client_input)
    if fresh_text is None:
        return None
    selection = await quota_rebalance_exclusions(balancer, request, account_id=account_id)
    if selection is None:
        return None
    owner_used, excluded_ids = selection
    original_fingerprint = request.input_full_fingerprint
    request.fresh_upstream_request_text = fresh_text
    request.fresh_upstream_request_is_retry_safe = True
    text = _install_fresh_replay_body(request, fresh_text, account_neutral=True)
    # Empty wire metadata is not conversation content. Keep the client's
    # original fingerprint so its next full-history turn still anchors.
    request.input_full_fingerprint = original_fingerprint
    request.excluded_account_ids.update(excluded_ids)
    request.affinity_policy = replace(request.affinity_policy, reallocate_sticky=True)
    request.previous_response_owner_account_id = None
    request.previous_response_owner_lookup_outcome = None
    logger.info(
        "websocket_quota_rebalance source_usage_pct=%s full_context=true",
        owner_used,
    )
    return text


async def quota_rebalance_exclusions(
    balancer: LoadBalancer, request: _WebSocketRequestState, *, account_id: str
) -> tuple[float, set[str]] | None:
    """Find fresh lower-quota candidates without mutating health or leases."""
    key = request.api_key
    scope = set(key.assigned_account_ids) if key is not None and key.account_assignment_scope_enabled else None
    inputs = await balancer._load_selection_inputs(
        model=request.model, service_tier=request.requested_service_tier, account_ids=scope
    )
    now = balancer._clock.time()
    states, _ = _build_states(
        accounts=inputs.accounts,
        latest_primary=inputs.latest_primary,
        latest_secondary=inputs.latest_secondary,
        latest_monthly=inputs.latest_monthly,
        runtime=deepcopy(balancer._runtime),
        now=now,
        ignore_standard_quota_account_ids=inputs.ignore_standard_quota_account_ids,
        soft_drain_enabled=False,
        log_weight_transitions=False,
    )
    fresh_ids: set[str] = set()
    for state in states:
        entries = [
            entry
            for history in (inputs.latest_primary, inputs.latest_secondary, inputs.latest_monthly)
            if (entry := history.get(state.account_id)) is not None
            and entry.window_minutes
            and (entry.reset_at is None or entry.reset_at > now)
        ]
        if entries and all(
            math.isfinite(entry.used_percent)
            and 0 <= now - entry.recorded_at.replace(tzinfo=timezone.utc).timestamp() <= 300
            for entry in entries
        ):
            fresh_ids.add(state.account_id)
    owner = next((state for state in states if state.account_id == account_id), None)
    owner_used = quota_first_consumption(owner) if owner is not None else None
    if owner is None or account_id not in fresh_ids or owner_used is None or owner_used < 50:
        return None
    candidates = [
        state
        for state in states
        if state.account_id != account_id
        and state.account_id in fresh_ids
        and state.account_id not in request.excluded_account_ids
        and state.status == AccountStatus.ACTIVE
        and not state.subscription_exhausted
        and not state.ignore_standard_quota
        and state.routing_policy == "normal"
        and (used := quota_first_consumption(state)) is not None
        and (owner.subscription_exhausted or owner_used - used >= 25)
        and select_account(
            [replace(state)], routing_strategy="quota_first_balanced", allow_backoff_fallback=False
        ).account
        is not None
    ]
    if not candidates:
        return None
    legacy_key = request.affinity_policy.legacy_selection_key
    if legacy_key is not None:
        async with balancer._repo_factory() as repos:
            # Even an abandoned legacy row is left alone here. The ordinary
            # connector still performs its authoritative owner check, including
            # an owner published after this read.
            if await repos.sticky_sessions.get_entry(legacy_key, kind=StickySessionKind.CODEX_SESSION) is not None:
                return None
    candidate_ids = {state.account_id for state in candidates}
    return owner_used, {state.account_id for state in states if state.account_id not in candidate_ids}


def _complete_context_text(
    request: _WebSocketRequestState,
    continuity: _WebSocketContinuityState,
    client_input: JsonValue,
    *,
    pending_tool_calls: dict[str, str] | None = None,
) -> str | None:
    if (
        not isinstance(client_input, list)
        or request.request_text is None
        or continuity.last_completed_response_id != request.previous_response_id
        or continuity.last_completed_input_count <= 0
    ):
        return None
    original_payload = json.loads(request.request_text)
    original_payload["input"] = client_input
    original_payload.pop("previous_response_id", None)
    original_text = json.dumps(original_payload, separators=(",", ":"), ensure_ascii=True)
    if (
        _fingerprint_input_items(client_input) == request.input_full_fingerprint
        and len(original_text.encode("utf-8")) <= _upstream_response_create_max_bytes()
        and native_quota_context_is_complete(
            original_payload,
            stored_count=continuity.last_completed_input_count,
            pending_tool_calls=pending_tool_calls,
        )
    ):
        return original_text
    if pending_tool_calls:
        return None
    items = deepcopy(client_input)
    # Actual Responses output includes empty annotation/logprob arrays. They
    # carry no context but are not accepted by the strict fresh-replay shape.
    # Never remove nonempty metadata, reasoning, tools or account references.
    for item in items:
        if not isinstance(item, dict) or item.get("role") != "assistant" or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "output_text":
                for key in ("annotations", "logprobs"):
                    if part.get(key) == []:
                        del part[key]
    # Prove this is exactly the full input that request preparation anchored,
    # not a trimmed, rewritten or partially recovered conversation.
    if _fingerprint_input_items(items) != request.input_full_fingerprint:
        return None
    for item in items:
        if isinstance(item, dict) and item.get("role") == "assistant" and item.get("type") == "message":
            item.pop("id", None)
    # Reuse the validated/enforced request envelope, replacing only its input
    # and the anchor which belonged to the old account.
    payload = json.loads(request.request_text)
    payload["input"] = items
    payload.pop("previous_response_id", None)
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    if len(text.encode("utf-8")) > _upstream_response_create_max_bytes():
        return None
    if not _websocket_request_text_is_account_neutral_fresh_replay(text):
        return None
    if not _websocket_full_resend_retains_prior_output(
        continuity, items, stored_count=continuity.last_completed_input_count
    ):
        return None
    return text
