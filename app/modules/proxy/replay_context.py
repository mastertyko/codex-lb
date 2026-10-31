"""Shared full-context replay proofs for HTTP and WebSocket handoffs."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, cast

from app.core.types import JsonValue
from app.modules.proxy.replay_safety import (
    project_responses_input_for_account_neutral_fresh_replay,
    responses_input_suffix_retains_prior_output,
    responses_payload_is_account_neutral_fresh_replay,
)

if TYPE_CHECKING:
    from app.modules.proxy._service.support import _WebSocketContinuityState, _WebSocketRequestState


def request_text_is_account_neutral_fresh_replay(request_text: str | None) -> bool:
    if not isinstance(request_text, str):
        return False
    try:
        payload = json.loads(request_text)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    event_type = payload.get("type")
    if event_type is not None and event_type != "response.create":
        return False
    payload.pop("type", None)
    return responses_payload_is_account_neutral_fresh_replay(cast(dict[str, JsonValue], payload))


def full_resend_retains_prior_output(
    continuity_state: _WebSocketContinuityState,
    input_items: list[JsonValue],
    *,
    stored_count: int,
) -> bool:
    # Direct WebSocket done-event metadata is not a complete output manifest.
    # Even a later assistant boundary cannot override known pending work.
    if (
        continuity_state.last_pending_function_call_ids
        or continuity_state.last_pending_tool_call_types
        or continuity_state.pending_async_tool_calls
    ):
        return False
    projection = project_responses_input_for_account_neutral_fresh_replay(
        input_items,
        stored_count=stored_count,
        preserve_developer_message_ids=True,
    )
    return projection is not None and responses_input_suffix_retains_prior_output(
        projection.input_items,
        stored_count=projection.stored_prefix_count,
        canonical_lite_developer_index=projection.canonical_lite_developer_index,
    )


def install_fresh_replay_body(
    request_state: "_WebSocketRequestState",
    fresh_request_text: str,
    *,
    account_neutral: bool,
    release_owner_pin: bool = True,
) -> str:
    """Swap the retained fresh body in and re-derive the owner requirement from it.

    The anchored body pinned the request to the anchor's owner
    (``replay_required_account_id`` / ``preferred_account_id``, bound at
    dispatch and on connect). The fresh body carries no anchor: an
    account-neutral one is free to move, a non-neutral one stays with the
    owner that was already required or preferred. Every path that installs
    the fresh body must reconcile the pin with it; a stale pin under a body
    that turned neutral is what let an accepted transport-close replay exclude
    the very account its reconnect still required.

    A turn-state owner is a session pin, not a body pin. The session loop
    re-resolves it before every reconnect and ``_connect_proxy_websocket``
    hard-requires it (``turn_state_owner_required``) whenever the session
    carries an owner, so the fresh body cannot release it: clearing it here
    only hid the requirement from the exclusion decision, and the replay then
    excluded the account its reconnect was about to require.

    ``release_owner_pin=False`` keeps both pins untouched for a replay whose
    anchor the proxy is not entitled to release (a client-supplied
    ``previous_response_id``): the fresh body is still what goes upstream,
    but it stays with the owner the anchored body was bound to.
    """
    replay_required_account_id = request_state.replay_required_account_id or request_state.preferred_account_id
    turn_state_owner_account_id = (
        request_state.preferred_account_id
        if request_state.affinity_policy.codex_session_source == "turn_state"
        else None
    )
    request_state.request_text = fresh_request_text
    request_state.previous_response_id = None
    if release_owner_pin:
        request_state.preferred_account_id = turn_state_owner_account_id
        request_state.replay_required_account_id = None if account_neutral else replay_required_account_id
    request_state.proxy_injected_previous_response_id = False
    request_state.fresh_upstream_request_is_retry_safe = False
    request_state.responses_lite_model = request_state.fresh_upstream_request_responses_lite_model
    refresh_request_input_fingerprint_from_text(request_state)
    return fresh_request_text


def refresh_request_input_fingerprint_from_text(request_state: _WebSocketRequestState) -> None:
    if not request_state.request_text:
        request_state.input_item_count = 0
        request_state.input_full_fingerprint = None
        return
    try:
        payload = json.loads(request_state.request_text)
    except json.JSONDecodeError:
        request_state.input_item_count = 0
        request_state.input_full_fingerprint = None
        return
    if not isinstance(payload, dict):
        request_state.input_item_count = 0
        request_state.input_full_fingerprint = None
        return
    input_items = payload.get("input")
    if not isinstance(input_items, list):
        request_state.input_item_count = 0
        request_state.input_full_fingerprint = None
        return
    request_state.input_item_count = len(input_items)
    request_state.input_full_fingerprint = sys.modules["app.modules.proxy.service"]._fingerprint_input_items(
        cast(list[JsonValue], input_items)
    )
