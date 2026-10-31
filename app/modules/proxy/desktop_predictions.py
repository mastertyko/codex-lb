"""Caller-owned Predictions on native Desktop connections; never pool failover."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import anyio
from fastapi import Request, WebSocket
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.types import Message
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.core.auth.desktop_diagnostics import current_trace, emit
from app.core.auth.desktop_identity import DesktopIdentityPrincipal, parse_desktop_identity_principal
from app.core.auth.desktop_oauth import (
    DesktopOAuthAdmission,
    authenticate_desktop_oauth,
    recheck_desktop_grant,
)
from app.core.clients.desktop_predictions import PREDICTION_BASE_URL, stream_prediction
from app.core.clients.proxy import ProxyResponseError
from app.core.clients.proxy_websocket import UpstreamWebSocket, connect_responses_websocket
from app.core.config.settings import get_settings
from app.core.errors import openai_error
from app.core.exceptions import AppError
from app.core.ingress_limits import MAX_DECOMPRESSED_RESPONSES_BODY_BYTES
from app.core.openai.models import OpenAIResponse
from app.core.openai.requests import ResponsesRequest, extract_input_file_ids
from app.core.types import JsonValue
from app.core.upstream_proxy import ResolvedUpstreamRoute
from app.core.utils.shared_future import _await_result_deferring_cancellation, _await_task_deferring_cancellation
from app.db.models import Account, AccountStatus
from app.db.session import detach_session_objects
from app.modules.api_keys.service import ApiKeyData
from app.modules.proxy._service.support import _StreamSettlement
from app.modules.proxy.api_key_usage import estimate_api_key_request_usage
from app.modules.proxy.request_policy import (
    apply_api_key_enforcement,
    normalize_responses_request_payload,
    validate_model_access,
)

if TYPE_CHECKING:
    from app.modules.proxy.service import ProxyService

_ORIGIN = PREDICTION_BASE_URL
_METADATA = "x-codex-turn-metadata"
_MAX_FRAME_BYTES = 16 * 1024 * 1024
_CLOSE_TIMEOUT_SECONDS = 5.0
_TERMINAL = {"response.completed", "response.failed", "response.incomplete", "error"}


def _error(message: str, *, status: int = 400) -> ProxyResponseError:
    reason = {
        "Unknown Prediction continuity": "unknown_continuity",
        "Prediction file references are unsupported": "files",
        "Prediction policy changed before dispatch": "policy_changed",
        "Prediction owner is unavailable": "owner",
        "Prediction owner changed": "owner",
        "Prediction owner capacity is unavailable": "capacity",
        "Desktop lane cannot change": "lane",
        "Prediction timed out": "timeout",
    }.get(message, "protocol")
    emit("denied", status=status, reason=reason)
    return ProxyResponseError(status, openai_error("desktop_prediction_denied", message))


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def _object(raw: str, *, limit: int = _MAX_FRAME_BYTES) -> dict[str, JsonValue]:
    if len(raw.encode()) > limit:
        raise _error("Desktop frame is too large", status=413)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        raise _error("Invalid Desktop JSON") from None
    if not isinstance(value, dict):
        raise _error("Expected Desktop JSON object")
    return cast(dict[str, JsonValue], value)


def prediction_lane(payload: Mapping[str, JsonValue]) -> bool:
    metadata = payload.get("client_metadata", {})
    if not isinstance(metadata, dict):
        raise _error("Invalid Desktop metadata")
    raw = metadata.get(_METADATA)
    if raw is None:
        return False
    if not isinstance(raw, str):
        raise _error("Invalid Desktop turn metadata")
    source = _object(raw, limit=64 * 1024)
    values = (source.get("thread_source"), source.get("turn_trigger"))
    if any(value is not None and (not isinstance(value, str) or not value) for value in values):
        raise _error("Invalid Desktop source")
    if "composer_predictions" in values:
        prewarm = (
            values == ("composer_predictions", None)
            and "turn_trigger" not in source
            and payload.get("generate") is False
        )
        if values != ("composer_predictions", "composer_predictions") and not prewarm:
            raise _error("Conflicting Desktop source")
        return True
    return False


def _caller_headers(headers: Mapping[str, str], admission: DesktopOAuthAdmission) -> dict[str, str]:
    # Never carry pool continuity, credentials or client-selected authority.
    allowed = {
        "user-agent",
        "originator",
        "version",
        "openai-beta",
        "openai-alpha",
        "x-codex-beta-features",
        "x-codex-installation-id",
    }
    result = {name: value for name, value in headers.items() if name.lower() in allowed}
    if admission.credentials.attestation is not None:
        result["x-oai-attestation"] = admission.credentials.attestation
    return result


def _check_owner(account: Account, principal: DesktopIdentityPrincipal, api_key: ApiKeyData) -> None:
    if (
        account.delete_requested_at is not None
        or account.chatgpt_user_id != principal.user_id
        or account.chatgpt_account_id != principal.workspace_id
        or account.status not in (AccountStatus.ACTIVE, AccountStatus.PAUSED)
        or (api_key.account_assignment_scope_enabled and account.id not in api_key.assigned_account_ids)
    ):
        raise _error("Prediction owner is unavailable", status=503)


@dataclass(frozen=True, slots=True)
class _Owner:
    account_id: str
    route: ResolvedUpstreamRoute | None


@asynccontextmanager
async def _owner(service: ProxyService, admission: DesktopOAuthAdmission) -> AsyncIterator[_Owner]:
    emit("owner_lookup")

    async def lookup() -> Account:
        async with service._repo_factory() as repos:
            owners = await repos.accounts.find_desktop_owners(
                user_id=admission.principal.user_id, workspace_id=admission.principal.workspace_id
            )
            if len(owners) != 1:
                raise _error("Prediction owner is unavailable", status=403)
            account = owners[0]
            _check_owner(account, admission.principal, admission.api_key)
            detach_session_objects(repos.accounts.session)
        return account

    # A cancelled pool pre-ping can lose the checkout before AsyncSession owns
    # it. Finish checkout/query/teardown in one owned operation, then cancel
    # before acquiring capacity or dispatching upstream work.
    account, cancellation = await _await_result_deferring_cancellation(lookup())
    if cancellation is not None:
        raise cancellation
    account_id = account.id
    emit("owner_validated")
    lease = await service._load_balancer.acquire_account_lease(
        account_id, kind="stream", api_key_id=admission.api_key.id
    )
    if lease is None:
        raise _error("Prediction owner capacity is unavailable", status=429)
    try:
        route = await service._resolve_upstream_route_for_account(account, operation="desktop_prediction")
        await _recheck_owner(service, admission, account_id)
        emit("owner_ready")
        yield _Owner(account_id, route)
    finally:
        task = asyncio.create_task(service._load_balancer.release_account_lease(lease))
        _, cancellation = await _await_task_deferring_cancellation(task)
        if cancellation is not None:
            raise cancellation


async def _recheck_owner(service: ProxyService, admission: DesktopOAuthAdmission, account_id: str) -> ApiKeyData:
    async def recheck() -> ApiKeyData:
        parse_desktop_identity_principal(admission.credentials.access_token, admission.principal.workspace_id)
        key = await recheck_desktop_grant(admission.principal, admission.api_key.id)
        async with service._repo_factory() as repos:
            owners = await repos.accounts.find_desktop_owners(
                user_id=admission.principal.user_id, workspace_id=admission.principal.workspace_id
            )
            if len(owners) != 1 or owners[0].id != account_id:
                raise _error("Prediction owner changed", status=403)
            _check_owner(owners[0], admission.principal, key)
        parse_desktop_identity_principal(admission.credentials.access_token, admission.principal.workspace_id)
        return key

    key, cancellation = await _await_result_deferring_cancellation(recheck())
    if cancellation is not None:
        raise cancellation
    return key


async def _recheck_dispatch(
    service: ProxyService, admission: DesktopOAuthAdmission, account_id: str, request: ResponsesRequest
) -> None:
    key = await _recheck_owner(service, admission, account_id)
    validate_model_access(key, request.model)
    checked = request.model_copy(deep=True)
    apply_api_key_enforcement(checked, key)
    if checked.to_payload() != request.to_payload():
        raise _error("Prediction policy changed before dispatch", status=403)
    emit("policy_allowed")


async def _prepare(
    admission: DesktopOAuthAdmission, payload: Mapping[str, JsonValue], known_responses: set[str]
) -> tuple[DesktopOAuthAdmission, ResponsesRequest]:
    fresh = await authenticate_desktop_oauth(admission.credentials, previous=admission)
    request = normalize_responses_request_payload(dict(payload), openai_compat=True)
    if request.conversation or (
        request.previous_response_id is not None and request.previous_response_id not in known_responses
    ):
        raise _error("Unknown Prediction continuity")
    if extract_input_file_ids(request.input):
        raise _error("Prediction file references are unsupported")
    from app.core.config.settings_cache import get_settings_cache

    policy = await get_settings_cache().get()
    apply_api_key_enforcement(request, fresh.api_key, prohibit_fast_mode=policy.prohibit_fast_mode)
    validate_model_access(fresh.api_key, request.model)
    emit("policy_allowed")
    if request.prompt_cache_key:
        request.prompt_cache_key = f"desktop-prediction:{fresh.pool_namespace}:{request.prompt_cache_key}"
    return fresh, request


def _capture_settlement(event: dict[str, JsonValue], settlement: _StreamSettlement, known: set[str]) -> None:
    response = event.get("response")
    if not isinstance(response, dict):
        return
    parsed = OpenAIResponse.model_validate(response)
    if parsed.id and event.get("type") in _TERMINAL:
        if len(known) >= 512:
            known.pop()
        known.add(parsed.id)
    if parsed.usage is not None:
        settlement.input_tokens = parsed.usage.input_tokens
        settlement.output_tokens = parsed.usage.output_tokens
        details = parsed.usage.input_tokens_details
        settlement.cached_input_tokens = details.cached_tokens if details else 0
    settlement.status = "success" if event.get("type") == "response.completed" else "failed"


@asynccontextmanager
async def _reservation(
    service: ProxyService, admission: DesktopOAuthAdmission, request: ResponsesRequest
) -> AsyncIterator[_StreamSettlement]:
    reservation = await service._reserve_websocket_api_key_usage(
        admission.api_key,
        request_model=request.model,
        request_service_tier=request.service_tier,
        request_usage_budget=estimate_api_key_request_usage(request),
    )
    settlement = _StreamSettlement(status="failed", model=request.model, service_tier=request.service_tier)
    try:
        yield settlement
    finally:
        with anyio.CancelScope(shield=True):
            task = asyncio.create_task(
                service._settle_stream_api_key_usage(
                    admission.api_key,
                    reservation,
                    settlement,
                    request_id=str(uuid4()),
                    wait_for_settlement=True,
                )
            )
            _, cancellation = await _await_task_deferring_cancellation(task)
            if cancellation is not None:
                raise cancellation


async def prediction_http_response(
    request: Request, payload: Mapping[str, JsonValue], service: ProxyService, admission: DesktopOAuthAdmission
) -> Response | None:
    try:
        if (trace := current_trace()) is not None:
            trace.frame(payload)
        caller = prediction_lane(payload)
        if (trace := current_trace()) is not None:
            trace.classify(caller)
        if not caller:
            return None
        fresh, body = await _prepare(admission, payload, set())
        if body.stream is False:
            raise _error("Predictions require streaming")
        body.stream = True
    except (AppError, ProxyResponseError, ValidationError) as exc:
        status = exc.status_code if isinstance(exc, (AppError, ProxyResponseError)) else 400
        emit("denied", status=status, reason="validation" if isinstance(exc, ValidationError) else None)
        return JSONResponse(
            status_code=status, content=openai_error("desktop_prediction_denied", "Prediction request denied")
        )

    async def events() -> AsyncIterator[str]:
        try:
            async with _owner(service, fresh) as owner, _reservation(service, fresh, body) as settlement:
                await _recheck_dispatch(service, fresh, owner.account_id, body)
                emit("upstream_start")
                async with aclosing(
                    cast(
                        AsyncGenerator[str, None],
                        stream_prediction(
                            body,
                            _caller_headers(request.headers, fresh),
                            fresh.credentials.access_token,
                            fresh.principal.workspace_id,
                            route=owner.route,
                            timeout_seconds=get_settings().proxy_request_budget_seconds,
                        ),
                    )
                ) as upstream:
                    async for block in upstream:
                        for line in block.splitlines():
                            if line.startswith("data: ") and line[6:] != "[DONE]":
                                event = _object(line[6:])
                                if (trace := current_trace()) is not None:
                                    trace.observe(event)
                                _capture_settlement(event, settlement, set())
                        yield block
        except asyncio.CancelledError:
            emit("cancelled")
            raise
        except Exception as exc:
            emit("failed", status=exc.status_code if isinstance(exc, ProxyResponseError) else None, reason="transport")
            yield (
                'event: error\ndata: {"type":"error","error":{"code":"desktop_prediction_failed",'
                '"message":"Prediction is unavailable"}}\n\n'
            )

    return StreamingResponse(events(), media_type="text/event-stream")


async def _frame(websocket: WebSocket) -> dict[str, JsonValue]:
    text = await asyncio.wait_for(
        websocket.receive_text(), timeout=get_settings().proxy_downstream_websocket_idle_timeout_seconds
    )
    payload = _object(text, limit=MAX_DECOMPRESSED_RESPONSES_BODY_BYTES)
    if payload.get("type") != "response.create":
        raise _error("Expected response.create")
    if (trace := current_trace()) is not None:
        trace.frame(payload)
    return payload


async def _caller_websocket(
    websocket: WebSocket,
    first: dict[str, JsonValue],
    service: ProxyService,
    admission: DesktopOAuthAdmission,
    headers: Mapping[str, str],
) -> None:
    known: set[str] = set()
    upstream: UpstreamWebSocket | None = None
    payload = first
    async with _owner(service, admission) as owner:
        try:
            while True:
                caller = prediction_lane(payload)
                if (trace := current_trace()) is not None:
                    trace.classify(caller)
                if not caller:
                    raise _error("Desktop lane cannot change")
                fresh, body = await _prepare(admission, payload, known)
                async with _reservation(service, fresh, body) as settlement:
                    await _recheck_dispatch(service, fresh, owner.account_id, body)
                    if upstream is None:
                        emit("upstream_connect")
                        upstream = await connect_responses_websocket(
                            _caller_headers(headers, fresh),
                            fresh.credentials.access_token,
                            fresh.principal.workspace_id,
                            base_url=_ORIGIN,
                            route=owner.route,
                            allow_direct_egress=owner.route is None,
                            caller_owned=True,
                        )
                        emit("upstream_connected", status=101)
                        await _recheck_dispatch(service, fresh, owner.account_id, body)
                    loop = asyncio.get_running_loop()
                    deadline = loop.time() + get_settings().proxy_request_budget_seconds
                    emit("upstream_start")
                    await asyncio.wait_for(
                        upstream.send_text(json.dumps({**body.to_payload(), "type": "response.create"})),
                        timeout=max(0.0, deadline - loop.time()),
                    )
                    downstream = asyncio.create_task(websocket.receive())
                    upstream_task = None
                    try:
                        while True:
                            upstream_task = asyncio.create_task(upstream.receive())
                            done, _ = await asyncio.wait(
                                {downstream, upstream_task},
                                timeout=max(0.0, deadline - loop.time()),
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if downstream in done:
                                message = downstream.result()
                                if message["type"] == "websocket.disconnect":
                                    emit("cancelled")
                                    return
                                raise _error("Only one active Prediction is supported")
                            if upstream_task not in done:
                                raise _error("Prediction timed out", status=504)
                            event_message = upstream_task.result()
                            if event_message.kind != "text" or event_message.text is None:
                                raise _error("Prediction upstream closed", status=502)
                            event = _object(event_message.text)
                            if (trace := current_trace()) is not None:
                                trace.observe(event)
                            terminal = event.get("type") in _TERMINAL
                            if terminal:
                                _capture_settlement(event, settlement, known)
                            if terminal:
                                terminal_text = event_message.text
                                break
                            await asyncio.wait_for(
                                websocket.send_text(event_message.text), timeout=max(0.0, deadline - loop.time())
                            )
                    finally:
                        tasks = [downstream, *([upstream_task] if upstream_task is not None else [])]
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        with anyio.CancelScope(shield=True):
                            await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.wait_for(websocket.send_text(terminal_text), timeout=max(0.0, deadline - loop.time()))
                payload = await _frame(websocket)
        except WebSocketDisconnect:
            emit("disconnected")
            return
        except asyncio.CancelledError:
            emit("cancelled")
            raise
        except Exception as exc:
            emit("failed", status=exc.status_code if isinstance(exc, ProxyResponseError) else None)
            raise _error("Prediction transport failed", status=502) from None
        finally:
            if upstream is not None:
                with anyio.CancelScope(shield=True):
                    try:
                        await asyncio.wait_for(upstream.close(), timeout=_CLOSE_TIMEOUT_SECONDS)
                    except Exception:
                        raise _error("Prediction cleanup failed", status=502) from None


async def route_desktop_websocket(
    websocket: WebSocket,
    headers: dict[str, str],
    service: ProxyService,
    admission: DesktopOAuthAdmission,
    *,
    codex_session_affinity: bool,
    client_ip: str | None,
    synthesized_turn_state: str | None,
    capability_header_values: tuple[str, ...],
) -> None:
    try:
        first = await _frame(websocket)
        caller = prediction_lane(first)
        if (trace := current_trace()) is not None:
            trace.classify(caller)
        if caller:
            if capability_header_values:
                raise _error("Predictions do not support pool capabilities")
            await _caller_websocket(websocket, first, service, admission, headers)
            return

        pending: dict[str, JsonValue] | None = first
        receive_task: asyncio.Task[Message] | None = None

        async def receive_and_validate() -> Message:
            nonlocal pending
            replayed_first = pending is not None
            if pending is not None:
                value, pending = pending, None
                message: Message = {"type": "websocket.receive", "text": json.dumps(value)}
            else:
                message = await websocket.receive()
            if message["type"] == "websocket.receive":
                try:
                    raw = message.get("text")
                    if not isinstance(raw, str):
                        raise _error("Desktop frames must be text")
                    value = _object(raw, limit=MAX_DECOMPRESSED_RESPONSES_BODY_BYTES)
                    if value.get("type") == "response.create":
                        if not replayed_first and (trace := current_trace()) is not None:
                            trace.frame(value)
                            trace.classify(prediction_lane(value))
                        if prediction_lane(value):
                            raise _error("Desktop lane cannot change")
                        await authenticate_desktop_oauth(admission.credentials, previous=admission)
                except (AppError, ProxyResponseError):
                    emit("denied", reason="auth")
                    await websocket.close(code=1008)
                    return {"type": "websocket.disconnect", "code": 1008}
            return message

        async def guarded_receive() -> Message:
            nonlocal receive_task
            if receive_task is None:
                receive_task = asyncio.create_task(receive_and_validate())
            task = receive_task
            try:
                # The pool polls receive() with a short timeout. Preserve a
                # consumed frame and its bounded auth check across those polls.
                message = await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.cancelled():
                    receive_task = None
                raise
            except Exception:
                receive_task = None
                raise
            receive_task = None
            return message

        guarded = WebSocket(websocket.scope, receive=guarded_receive, send=websocket.send)
        guarded.client_state = WebSocketState.CONNECTED
        guarded.application_state = WebSocketState.CONNECTED
        try:
            await service.proxy_responses_websocket(
                guarded,
                headers,
                codex_session_affinity=codex_session_affinity,
                openai_cache_affinity=True,
                api_key=admission.api_key,
                client_ip=client_ip,
                synthesized_turn_state=synthesized_turn_state,
                capability_header_values=capability_header_values,
            )
        finally:
            if receive_task is not None:
                if not receive_task.done():
                    receive_task.cancel()
                with anyio.CancelScope(shield=True):
                    await asyncio.gather(receive_task, return_exceptions=True)
    except WebSocketDisconnect:
        emit("disconnected")
        return
    except (AppError, ProxyResponseError, ValidationError, TimeoutError):
        emit("failed", reason="protocol")
        if websocket.client_state == WebSocketState.DISCONNECTED:
            return
        if websocket.application_state == WebSocketState.CONNECTED:
            await asyncio.wait_for(
                websocket.send_json(
                    {"type": "error", **openai_error("desktop_prediction_denied", "Desktop request denied")}
                ),
                timeout=2,
            )
            await asyncio.wait_for(websocket.close(code=1008), timeout=2)
