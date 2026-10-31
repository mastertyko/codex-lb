"""Conservative quota moves of unsent, complete WebSocket conversation turns."""

from __future__ import annotations

import logging
from dataclasses import replace

from app.core.types import JsonValue
from app.db.models import StickySessionKind
from app.modules.proxy._service.support import _WebSocketContinuityState, _WebSocketRequestState
from app.modules.proxy._service.websocket.helpers import _install_fresh_replay_body
from app.modules.proxy.load_balancer import LoadBalancer
from app.modules.proxy.quota_rebalance import complete_context_text, quota_rebalance_exclusions

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
    fresh_text = complete_context_text(request, continuity, client_input)
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
