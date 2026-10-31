"""Move only complete, idle HTTP bridge turns to a fresher subscription."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import aiohttp

from app.core.clients.proxy import ProxyResponseError
from app.core.errors import openai_error
from app.core.types import JsonValue
from app.db.models import DashboardSettings
from app.modules.proxy._service.http_bridge.helpers import _bind_http_bridge_proxy_injected_anchor
from app.modules.proxy._service.support import _HTTPBridgeSession, _WebSocketContinuityState, _WebSocketRequestState
from app.modules.proxy.durable_bridge_coordinator import DurableBridgeLookup

if TYPE_CHECKING:
    from app.modules.proxy.service import ProxyService

logger = logging.getLogger(__name__)


def prepare_http_quota_rebalance(
    session: _HTTPBridgeSession, request: _WebSocketRequestState, client_input: JsonValue
) -> str | None:
    from app.modules.proxy._service.http_bridge.service_stubs import _input_prefix_matches_stored_context
    from app.modules.proxy._service.websocket.quota_rebalance import _complete_context_text

    if (
        session.key.affinity_kind not in {"thread_header", "prompt_cache"}
        or not request.proxy_injected_previous_response_id
        or request.require_security_work_authorized
        or request.affinity_policy.require_unambiguous_account
        or request.file_required_preferred_account
        or request.source_route_excluded
        or request.steering_parent_response_id is not None
        or request.replay_count
        or session.pending_async_tool_calls
        or session.last_completed_response_account_id != session.account.id
        or not _input_prefix_matches_stored_context(
            client_input,
            stored_count=session.last_completed_input_count,
            stored_fingerprint=session.last_completed_input_prefix_fingerprint,
        )
    ):
        return None
    return _complete_context_text(
        request,
        _WebSocketContinuityState(
            last_completed_response_id=session.last_completed_response_id,
            last_completed_input_count=session.last_completed_input_count,
        ),
        client_input,
        pending_tool_calls=session.last_pending_tool_calls,
    )


async def rebalance_http_bridge(
    proxy: ProxyService,
    session: _HTTPBridgeSession,
    request: _WebSocketRequestState,
    text: str,
    *,
    settings: DashboardSettings,
) -> str:
    from app.modules.proxy._service.websocket.helpers import _install_fresh_replay_body
    from app.modules.proxy._service.websocket.quota_rebalance import quota_rebalance_exclusions

    fresh_text = request.quota_rebalance_request_text
    request.quota_rebalance_request_text = None
    if fresh_text is None or settings.routing_strategy != "quota_first_balanced":
        return text
    owner_id = session.account.id
    selection = await quota_rebalance_exclusions(proxy._load_balancer, request, account_id=owner_id)
    if selection is None:
        return text
    owner_used, excluded_ids = selection
    async with session.lifecycle_lock:
        async with proxy._http_bridge_lock:
            if proxy._http_bridge_sessions.get(session.key) is not session:
                return text
        async with session.pending_lock:
            if (
                session.closed
                or session.handoff_in_progress
                or session.upstream_control.retire_after_drain
                or session.account.id != owner_id
                or session.last_completed_response_id != request.previous_response_id
                or session.last_completed_response_account_id != owner_id
                or session.pending_requests
                or session.queued_request_count
                or session.admission_waiter_count != 1
                or session.pending_async_tool_calls
                or request.operation_id is not None
                or request.response_create_attempt_count
            ):
                return text
        if prepare_http_quota_rebalance(session, request, json.loads(fresh_text)["input"]) != fresh_text:
            return text
        original_fingerprint = request.input_full_fingerprint
        request.fresh_upstream_request_text = fresh_text
        request.fresh_upstream_request_is_retry_safe = True
        installed = _install_fresh_replay_body(request, fresh_text, account_neutral=True)
        request.input_full_fingerprint = original_fingerprint
        request.hard_continuity_anchor = False
        request.previous_response_owner_account_id = None
        request.previous_response_owner_lookup_outcome = None
        _bind_http_bridge_proxy_injected_anchor(proxy, request, response_id=None)
        request.excluded_account_ids.update(excluded_ids)
        selection_affinity = replace(request.affinity_policy, reallocate_sticky=True)
        request.affinity_policy = selection_affinity
        try:
            await proxy._reconnect_http_bridge_session(
                session,
                request_state=request,
                restart_reader=True,
                selection_affinity=selection_affinity,
                dashboard_settings=settings,
            )
        except BaseException as exc:
            # Reconnect can fail after its old reader stopped but before swap.
            # The existing close owner shields socket/lease cleanup on cancellation.
            await proxy._close_http_bridge_session(session)
            if isinstance(exc, (aiohttp.ClientError, OSError, TimeoutError)):
                raise ProxyResponseError(
                    502,
                    openai_error("upstream_unavailable", "HTTP bridge quota handoff connection failed"),
                ) from exc
            raise
        logger.info("http_bridge_quota_rebalance source_usage_pct=%s full_context=true", owner_used)
        return installed


async def prepare_cold_http_quota_rebalance(
    proxy: ProxyService,
    request: _WebSocketRequestState,
    lookup: DurableBridgeLookup,
    *,
    fresh_text: str,
) -> tuple[str, set[str]] | None:
    """Prove a cold full resend before the ordinary fenced session claim."""
    from app.modules.proxy._service.http_bridge.service_stubs import _input_prefix_matches_stored_context
    from app.modules.proxy._service.response_create import _upstream_response_create_max_bytes
    from app.modules.proxy._service.websocket.quota_rebalance import quota_rebalance_exclusions
    from app.modules.proxy.quota_context import native_quota_context_is_complete

    if (
        lookup.account_id is None
        or lookup.latest_response_id is None
        or lookup.latest_input_item_count is None
        or request.require_security_work_authorized
        or request.affinity_policy.require_unambiguous_account
        or request.file_required_preferred_account
        or request.source_route_excluded
        or request.steering_parent_response_id is not None
        or request.replay_count
        or request.operation_id is not None
        or request.response_create_attempt_count
        or len(fresh_text.encode("utf-8")) > _upstream_response_create_max_bytes()
    ):
        return None
    payload = json.loads(fresh_text)
    if not _input_prefix_matches_stored_context(
        payload.get("input"),
        stored_count=lookup.latest_input_item_count,
        stored_fingerprint=lookup.latest_input_full_fingerprint,
    ) or not native_quota_context_is_complete(
        payload,
        stored_count=lookup.latest_input_item_count,
        pending_tool_calls=lookup.latest_pending_tool_calls,
    ):
        return None
    selection = await quota_rebalance_exclusions(proxy._load_balancer, request, account_id=lookup.account_id)
    if selection is None:
        return None
    return fresh_text, selection[1]
