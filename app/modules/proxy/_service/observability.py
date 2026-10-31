from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Callable, Literal, cast
from uuid import uuid4

from app.core.config.settings import get_settings
from app.core.metrics.prometheus import (
    PROMETHEUS_AVAILABLE,
    continuity_fail_closed_total,
    continuity_owner_resolution_total,
    continuity_replay_rejected_total,
    http_bridge_routing_total,
    upstream_reasoning_replay_400_total,
    upstream_transport_decisions_total,
)
from app.core.openai.requests import ResponsesCompactRequest, ResponsesRequest, canonicalized_tools
from app.core.types import JsonValue
from app.core.utils.json_guards import is_json_list
from app.core.utils.request_id import get_request_id
from app.modules.proxy._service.support import _hash_identifier, _hash_identifier_or_none
from app.modules.proxy.affinity import (
    _extract_model_class,
    _prompt_cache_key_from_request_model,
    _sticky_key_from_session_header,
)

if TYPE_CHECKING:
    from app.modules.proxy._service.support import _WebSocketRequestState, _WebSocketUpstreamControl


_WebSocketCloseOutcome = Literal[
    "unknown", "closed", "transport_error", "timeout", "reconnect", "cancelled", "client_disconnected", "reader_error"
]


logger = logging.getLogger("app.modules.proxy.service")


def _service_global(name: str, fallback: Any) -> Any:
    service_module = sys.modules.get("app.modules.proxy.service")
    if service_module is None:
        return fallback
    return getattr(service_module, name, fallback)


def _service_get_settings() -> Any:
    return cast(Callable[[], Any], _service_global("get_settings", get_settings))()


def record_http_bridge_routing(*, stage: str, reason: str) -> None:
    if http_bridge_routing_total is not None:
        http_bridge_routing_total.labels(stage=stage, reason=reason).inc()
    logger.info(
        "http_bridge_routing stage=%s reason=%s request_id=%s",
        stage,
        reason,
        get_request_id(),
    )


def _record_upstream_transport_decision(
    *,
    downstream_transport: str,
    upstream_transport: str | None,
    policy: str,
    sticky: bool,
    status: str,
) -> None:
    if upstream_transport_decisions_total is None:
        return
    upstream_transport_decisions_total.labels(
        downstream_transport=downstream_transport,
        upstream_transport=upstream_transport or "unknown",
        policy=policy,
        sticky="true" if sticky else "false",
        status="success" if status == "success" else "error",
    ).inc()


def _is_reasoning_replay_rejection(
    *,
    code: str,
    http_status: int | None,
    message: str | None,
) -> bool:
    """Return whether upstream rejected replayed reasoning items with a 400.

    Observation only: a forked thread that replays reasoning ciphertext minted
    for another account dies on ChatGPT's 400 and is undetectable from ids,
    so this predicate feeds ``codex_lb_upstream_reasoning_replay_400_total``
    to size that residual. It never alters classification, account health,
    or failover. Without an HTTP status (terminal ``error`` /
    ``response.failed`` frames) only the ``invalid_request_error`` code
    qualifies.
    """
    if http_status is None:
        if code != "invalid_request_error":
            return False
    elif http_status != 400:
        return False
    return "reasoning" in (message or "").lower()


def _record_upstream_reasoning_replay_rejection() -> None:
    if PROMETHEUS_AVAILABLE and upstream_reasoning_replay_400_total is not None:
        upstream_reasoning_replay_400_total.inc()
    logger.info("Counted upstream reasoning replay rejection request_id=%s", get_request_id())


def _observe_terminal_stream_error_frame(code: str | None, message: str | None) -> None:
    """Count a reasoning-replay rejection carried by a terminal ``error``/``response.failed`` frame.

    Runs where the frame is classified, before and independent of any account
    health write: ``invalid_request_error`` is never penalized, so
    ``_handle_stream_error`` never sees these frames. HTTP status rejections
    are counted by ``_handle_stream_error`` instead, so each upstream failure
    is counted exactly once.
    """
    if code is None:
        return
    if _is_reasoning_replay_rejection(code=code, http_status=None, message=message):
        _record_upstream_reasoning_replay_rejection()


def _maybe_log_proxy_request_shape(
    kind: str,
    payload: ResponsesRequest | ResponsesCompactRequest,
    headers: Mapping[str, str],
    *,
    sticky_kind: str | None = None,
    sticky_key_source: str | None = None,
    prompt_cache_key_set: bool | None = None,
    derivation_outcome: str | None = None,
    thread_cache_identity_mode: str | None = None,
    thread_cache_identity_from_key: bool | None = None,
) -> None:
    trace_channels = _service_get_settings().trace_channels
    if "shape" not in trace_channels:
        return

    request_id = get_request_id()
    prompt_cache_key = _prompt_cache_key_from_request_model(payload)
    prompt_cache_key_hash = _hash_identifier(prompt_cache_key) if isinstance(prompt_cache_key, str) else None
    prompt_cache_key_raw = (
        _truncate_identifier(prompt_cache_key)
        if "shape_raw_cache_key" in trace_channels and isinstance(prompt_cache_key, str)
        else None
    )

    extra_keys = sorted(payload.model_extra.keys()) if payload.model_extra else []
    fields_set = sorted(payload.model_fields_set)
    input_summary = _summarize_input(payload.input)
    header_keys = _interesting_header_keys(headers)
    session_header_present = _sticky_key_from_session_header(headers) is not None
    tools_hash = _tools_hash(payload)
    model_class = _extract_model_class(payload.model)

    logger.warning(
        "proxy_request_shape request_id=%s kind=%s model=%s stream=%s input=%s "
        "prompt_cache_key=%s prompt_cache_key_raw=%s fields=%s extra=%s headers=%s "
        "sticky_kind=%s sticky_key_source=%s derivation_outcome=%s prompt_cache_key_set=%s"
        " session_header_present=%s tools_hash=%s model_class=%s"
        " thread_cache_identity_mode=%s thread_cache_identity_from_key=%s",
        request_id,
        kind,
        payload.model,
        getattr(payload, "stream", None),
        input_summary,
        prompt_cache_key_hash,
        prompt_cache_key_raw,
        fields_set,
        extra_keys,
        header_keys,
        sticky_kind,
        sticky_key_source,
        derivation_outcome,
        prompt_cache_key_set,
        session_header_present,
        tools_hash,
        model_class,
        thread_cache_identity_mode,
        thread_cache_identity_from_key,
    )


def _maybe_log_proxy_request_payload(
    kind: str,
    payload: ResponsesRequest | ResponsesCompactRequest,
    headers: Mapping[str, str],
) -> None:
    if "payload" not in _service_get_settings().trace_channels:
        return

    request_id = get_request_id()
    payload_dict = payload.model_dump(mode="json", exclude_none=True)
    extra = payload.model_extra or {}
    if extra:
        payload_dict = {**payload_dict, "_extra": extra}
    header_keys = _interesting_header_keys(headers)
    payload_json = json.dumps(payload_dict, ensure_ascii=True, separators=(",", ":"))

    logger.warning(
        "proxy_request_payload request_id=%s kind=%s payload=%s headers=%s",
        request_id,
        kind,
        payload_json,
        header_keys,
    )


def _maybe_log_proxy_service_tier_trace(
    kind: str,
    *,
    requested_service_tier: str | None,
    actual_service_tier: str | None,
) -> None:
    if "service_tier" not in _service_get_settings().trace_channels:
        return

    logger.warning(
        "proxy_service_tier_trace request_id=%s kind=%s requested_service_tier=%s actual_service_tier=%s",
        get_request_id(),
        kind,
        requested_service_tier,
        actual_service_tier,
    )


def _record_continuity_owner_resolution(
    *,
    surface: str,
    source: str,
    outcome: str,
    previous_response_id: str | None,
    session_id: str | None,
) -> None:
    prometheus_available = bool(_service_global("PROMETHEUS_AVAILABLE", PROMETHEUS_AVAILABLE))
    counter = _service_global("continuity_owner_resolution_total", continuity_owner_resolution_total)
    if prometheus_available and counter is not None:
        counter.labels(
            surface=surface,
            source=source,
            outcome=outcome,
        ).inc()
    if outcome == "miss" or (outcome == "hit" and source == "request_cache"):
        return
    logger.log(
        logging.WARNING if outcome == "fail_closed" else logging.INFO,
        "continuity_owner_resolution surface=%s source=%s outcome=%s previous_response_id=%s session_id=%s",
        surface,
        source,
        outcome,
        _hash_identifier_or_none(previous_response_id),
        _hash_identifier_or_none(session_id),
    )


def _record_continuity_replay_rejected(*, surface: str, reason: str) -> None:
    """Count one refusal to move an unavailable owner's turn to another account.

    The recovery gate is a conjunction of independent proofs, so the caller
    reports the first one that refused; the paired ``owner_unavailable_replay_rejected``
    bridge event carries the request-scoped identifiers.
    """
    prometheus_available = bool(_service_global("PROMETHEUS_AVAILABLE", PROMETHEUS_AVAILABLE))
    counter = _service_global("continuity_replay_rejected_total", continuity_replay_rejected_total)
    if prometheus_available and counter is not None:
        counter.labels(surface=surface, reason=reason).inc()


def _format_continuity_fail_closed_diagnostics(
    *,
    previous_response_source: str | None,
    fresh_replay_available: bool | None,
    owner_lookup_source: str | None,
    owner_lookup_outcome: str | None,
    previous_response_age_seconds: int | None,
    same_session: bool | None,
) -> str | None:
    if all(
        value is None
        for value in (
            previous_response_source,
            fresh_replay_available,
            owner_lookup_source,
            owner_lookup_outcome,
            previous_response_age_seconds,
            same_session,
        )
    ):
        return None
    return " ".join(
        (
            f"previous_response_source={previous_response_source or 'unknown'}",
            "fresh_replay_available="
            f"{str(fresh_replay_available).lower() if fresh_replay_available is not None else 'unknown'}",
            f"owner_lookup_source={owner_lookup_source or 'unknown'}",
            f"owner_lookup_outcome={owner_lookup_outcome or 'unknown'}",
            "previous_response_age_seconds="
            f"{previous_response_age_seconds if previous_response_age_seconds is not None else 'unknown'}",
            f"same_session={str(same_session).lower() if same_session is not None else 'unknown'}",
        )
    )


def _record_continuity_fail_closed(
    *,
    surface: str,
    reason: str,
    previous_response_id: str | None,
    session_id: str | None = None,
    upstream_error_code: str | None = None,
    previous_response_source: str | None = None,
    fresh_replay_available: bool | None = None,
    owner_lookup_source: str | None = None,
    owner_lookup_outcome: str | None = None,
    previous_response_age_seconds: int | None = None,
    same_session: bool | None = None,
    request_state: _WebSocketRequestState | None = None,
    count_failure: bool = True,
) -> None:
    prometheus_available = bool(_service_global("PROMETHEUS_AVAILABLE", PROMETHEUS_AVAILABLE))
    counter = _service_global("continuity_fail_closed_total", continuity_fail_closed_total)
    if count_failure and prometheus_available and counter is not None:
        counter.labels(
            surface=surface,
            reason=reason,
        ).inc()
    diagnostics = _format_continuity_fail_closed_diagnostics(
        previous_response_source=previous_response_source,
        fresh_replay_available=fresh_replay_available,
        owner_lookup_source=owner_lookup_source,
        owner_lookup_outcome=owner_lookup_outcome,
        previous_response_age_seconds=previous_response_age_seconds,
        same_session=same_session,
    )
    correlation = ""
    if request_state is not None and request_state.transport == "websocket":
        category = (
            reason
            if reason
            in {
                "previous_response_not_found",
                "previous_response_not_found_malformed_param",
                "missing_tool_output",
                "owner_account_unavailable",
                "owner_lookup_failed",
                "stream_incomplete",
            }
            else "unknown"
        )
        upstream_error_code = (
            upstream_error_code
            if upstream_error_code
            in {
                "previous_response_not_found",
                "invalid_request_error",
                "stream_incomplete",
            }
            else "unknown"
        )
        correlation = (
            f" request_id={_hash_identifier_or_none(request_state.request_id) or 'unknown'}"
            f" conversation_id={_hash_identifier_or_none(request_state.conversation_id) or 'unknown'}"
            f" response_id={_hash_identifier_or_none(request_state.response_id) or 'unknown'}"
            f" connection_id={request_state.diagnostic_connection_id or 'unknown'}"
            f" category={category}"
        )
    logger.warning(
        "continuity_fail_closed surface=%s reason=%s previous_response_id=%s session_id=%s "
        "upstream_error_code=%s diagnostics=%s%s",
        surface,
        reason,
        _hash_identifier_or_none(previous_response_id) or ("unknown" if correlation else None),
        _hash_identifier_or_none(session_id) or ("unknown" if correlation else None),
        upstream_error_code,
        diagnostics,
        correlation,
    )


def _record_websocket_connection_opened(
    control: _WebSocketUpstreamControl, request_state: _WebSocketRequestState, *, now: float
) -> None:
    control.diagnostic_connection_id = _hash_identifier(uuid4().hex)
    control.diagnostic_opened_at = now
    logger.info(
        "websocket_connection_opened connection_id=%s request_id=%s session_id=%s conversation_id=%s",
        control.diagnostic_connection_id,
        _hash_identifier_or_none(request_state.request_id) or "unknown",
        _hash_identifier_or_none(request_state.session_id) or "unknown",
        _hash_identifier_or_none(request_state.conversation_id) or "unknown",
    )


def _record_websocket_connection_closed(
    control: _WebSocketUpstreamControl,
    *,
    now: float,
    outcome: _WebSocketCloseOutcome,
) -> None:
    if control.diagnostic_connection_id is None or control.diagnostic_opened_at is None:
        return
    logger.info(
        "websocket_connection_closed connection_id=%s outcome=%s lifetime_ms=%d",
        control.diagnostic_connection_id,
        outcome,
        max(0, int((now - control.diagnostic_opened_at) * 1000)),
    )


def _record_websocket_request_terminal(
    request_state: _WebSocketRequestState, *, status: str, now: float, response_id: str | None = None
) -> None:
    if request_state.transport != "websocket" or request_state.diagnostic_terminal_recorded:
        return
    request_state.diagnostic_terminal_recorded = True
    outcome = status if status in {"success", "error", "cancelled"} else "unknown"
    rejected_at = request_state.continuity_first_rejection_at
    recovered = outcome == "success" and rejected_at is not None and request_state.replay_count > 0
    elapsed_ms = max(0, int((now - rejected_at) * 1000)) if recovered and rejected_at is not None else "unknown"
    logger.info(
        "websocket_request_terminal request_id=%s session_id=%s conversation_id=%s response_id=%s "
        "connection_id=%s outcome=%s replay_count=%d recovered=%s elapsed_since_rejection_ms=%s",
        _hash_identifier_or_none(request_state.request_id) or "unknown",
        _hash_identifier_or_none(request_state.session_id) or "unknown",
        _hash_identifier_or_none(request_state.conversation_id) or "unknown",
        _hash_identifier_or_none(response_id or request_state.response_id) or "unknown",
        request_state.diagnostic_connection_id or "unknown",
        outcome,
        request_state.replay_count,
        str(recovered).lower(),
        elapsed_ms,
    )


def _summarize_input(items: JsonValue) -> str:
    if items is None:
        return "0"
    if isinstance(items, str):
        return "str"
    if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
        if not items:
            return "0"
        type_counts: dict[str, int] = {}
        for item in items:
            type_name = type(item).__name__
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        summary = ",".join(f"{key}={type_counts[key]}" for key in sorted(type_counts))
        return f"{len(items)}({summary})"
    return type(items).__name__


def _truncate_identifier(value: str, *, max_length: int = 96) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[:48]}...{value[-16:]}"


def _tools_hash(payload: ResponsesRequest | ResponsesCompactRequest) -> str | None:
    payload_tools = payload.to_payload().get("tools")
    if not is_json_list(payload_tools) or not payload_tools:
        return None
    # The wire payload keeps client tool entries byte-preserved (issue #1184),
    # so the affinity/observability hash canonicalizes locally to stay
    # insensitive to tool array order and object key order (change #228).
    serialized = json.dumps(
        canonicalized_tools(payload_tools),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _hash_identifier(serialized)


def _interesting_header_keys(headers: Mapping[str, str]) -> list[str]:
    allowlist = {
        "user-agent",
        "x-request-id",
        "request-id",
        "session-id",
        "session_id",
        "thread-id",
        "x-openai-client-id",
        "x-openai-client-version",
        "x-openai-client-arch",
        "x-openai-client-os",
        "x-openai-client-user-agent",
        "x-codex-session-id",
        "x-codex-conversation-id",
    }
    return sorted({key.lower() for key in headers.keys() if key.lower() in allowlist})
