"""Separate gateway admission from caller OAuth before ordinary proxy handling."""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import cast

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from app.core.auth.dependencies import validate_required_proxy_api_key_authorization
from app.core.auth.desktop_voice import DESKTOP_VOICE_PREFIX, DesktopVoiceCredentials
from app.core.clients.headers import CODEX_LB_KEY_HEADER
from app.core.errors import openai_error
from app.core.exceptions import ProxyAuthError
from app.core.middleware.path_rewrite import _canonicalize_backend_api_codex_path, redact_realtime_live_path
from app.core.types import JsonValue

logger = logging.getLogger(__name__)

_KEY_HEADER = CODEX_LB_KEY_HEADER.encode("ascii")
_MAX_ATTESTATION_BYTES = 16 * 1024
_CALLER_IDENTITY_HEADERS = frozenset(
    {b"authorization", b"chatgpt-account-id", b"x-oai-attestation", b"cookie", b"proxy-authorization", _KEY_HEADER}
)


class _GatewayRejectionReason(StrEnum):
    ROUTE_SUPPORT = "route_support"
    GATEWAY_HEADER = "gateway_header"
    CALLER_HEADER = "caller_header"
    BEARER_SYNTAX = "bearer_syntax"
    ACCOUNT_CONTEXT = "account_context"
    ATTESTATION_CARDINALITY = "attestation_cardinality"
    ATTESTATION_EMPTY = "attestation_empty"
    ATTESTATION_WHITESPACE = "attestation_whitespace"
    ATTESTATION_SIZE = "attestation_size"
    ATTESTATION_LIST = "attestation_list"
    ATTESTATION_CHARSET = "attestation_charset"
    KEY_VALIDATION = "key_validation"


def _is_supported_proxy_path(path: str) -> bool:
    return path.startswith(("/backend-api/codex/", "/backend-api/wham/", "/v1/", "/backend-api/files/")) or path.rstrip(
        "/"
    ) in {"/backend-api/files", "/backend-api/transcribe"}


def _single_header(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    values = [value.decode("latin-1") for key, value in headers if key.lower() == name]
    if len(values) != 1 or not values[0] or values[0] != values[0].strip():
        raise ProxyAuthError("Desktop gateway requires one unambiguous credential per header")
    return values[0]


def _unique_attestation_fields(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    fields: dict[str, JsonValue] = {}
    for name, value in pairs:
        if name in fields:
            raise ValueError("Duplicate attestation field")
        fields[name] = value
    return fields


def _is_native_attestation_envelope(value: str) -> bool:
    try:
        payload = cast(JsonValue, json.loads(value, object_pairs_hook=_unique_attestation_fields))
    except (ValueError, RecursionError):
        return False
    if not isinstance(payload, dict):
        return False
    version, status = payload.get("v"), payload.get("s")
    if type(version) is not int or version != 1 or type(status) is not int:
        return False
    if status == 0:
        return set(payload) == {"v", "s", "t"} and isinstance(payload["t"], str)
    return set(payload) == {"v", "s"} and 1 <= status <= 4


class DesktopVoiceCredentialMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = _canonicalize_backend_api_codex_path(scope["path"])
        voice_lane = path == DESKTOP_VOICE_PREFIX or path.startswith(DESKTOP_VOICE_PREFIX + "/")
        headers = scope.get("headers", [])
        has_key = any(name.lower() == _KEY_HEADER for name, _ in headers)
        if not has_key and not voice_lane:
            await self.app(scope, receive, send)
            return
        server_scope = scope
        if voice_lane:
            scope = dict(scope)
            redacted_path = redact_realtime_live_path(path)
            server_scope["path"] = redacted_path
            server_scope["raw_path"] = redacted_path.encode("utf-8")
            server_scope["query_string"] = b""
        sanitized_headers = [(name, value) for name, value in headers if name.lower() not in _CALLER_IDENTITY_HEADERS]
        # Even a rejected credential must not remain in the server-owned headers.
        server_scope["headers"] = sanitized_headers
        scope["headers"] = sanitized_headers
        reason = _GatewayRejectionReason.ROUTE_SUPPORT
        try:
            if not _is_supported_proxy_path(path):
                raise ProxyAuthError("Desktop gateway credentials are not supported on this route")
            reason = _GatewayRejectionReason.GATEWAY_HEADER
            key = _single_header(headers, _KEY_HEADER)
            reason = _GatewayRejectionReason.CALLER_HEADER
            authorization = _single_header(headers, b"authorization")
            reason = _GatewayRejectionReason.BEARER_SYNTAX
            scheme, separator, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not separator or not token or any(c.isspace() for c in token):
                raise ProxyAuthError("Desktop gateway requires a single caller Bearer credential")
            reason = _GatewayRejectionReason.GATEWAY_HEADER
            if "," in key or any(c.isspace() for c in key):
                raise ProxyAuthError("Desktop gateway credentials are ambiguous")
            reason = _GatewayRejectionReason.BEARER_SYNTAX
            if "," in token:
                raise ProxyAuthError("Desktop gateway credentials are ambiguous")
            reason = _GatewayRejectionReason.ACCOUNT_CONTEXT
            accounts = [value for name, value in headers if name.lower() == b"chatgpt-account-id"]
            if len(accounts) > 1:
                raise ProxyAuthError("Desktop gateway account context is ambiguous")
            account_id = _single_header(headers, b"chatgpt-account-id") if accounts else None
            if account_id is not None and ("," in account_id or any(c.isspace() for c in account_id)):
                raise ProxyAuthError("Desktop gateway account context is ambiguous")
            attestations = [value for name, value in headers if name.lower() == b"x-oai-attestation"]
            if len(attestations) > 1:
                reason = _GatewayRejectionReason.ATTESTATION_CARDINALITY
            elif attestations and not attestations[0]:
                reason = _GatewayRejectionReason.ATTESTATION_EMPTY
            else:
                reason = _GatewayRejectionReason.ATTESTATION_WHITESPACE
            attestation = _single_header(headers, b"x-oai-attestation") if attestations else None
            if attestation is not None:
                reason = _GatewayRejectionReason.ATTESTATION_SIZE
                if len(attestation) > _MAX_ATTESTATION_BYTES:
                    raise ProxyAuthError("Desktop gateway attestation is ambiguous or invalid")
                reason = _GatewayRejectionReason.ATTESTATION_LIST
                if "," in attestation and not _is_native_attestation_envelope(attestation):
                    raise ProxyAuthError("Desktop gateway attestation is ambiguous or invalid")
                reason = _GatewayRejectionReason.ATTESTATION_CHARSET
                if any(ord(c) <= 32 or ord(c) >= 127 for c in attestation):
                    raise ProxyAuthError("Desktop gateway attestation is ambiguous or invalid")
            reason = _GatewayRejectionReason.KEY_VALIDATION
            api_key = await validate_required_proxy_api_key_authorization(f"Bearer {key}")
        except ProxyAuthError as exc:
            logger.warning(
                "Desktop gateway rejected reason=%s transport=%s lane=%s",
                reason.value,
                scope["type"],
                "voice" if voice_lane else "ordinary",
            )
            response = JSONResponse(
                status_code=exc.status_code,
                content=openai_error("desktop_gateway_auth_invalid", "Invalid Desktop gateway credentials"),
            )
            if scope["type"] == "websocket":
                await WebSocket(scope, receive=receive, send=send).send_denial_response(response)
            else:
                await response(scope, receive, send)
            return

        # Mutate the shared ingress headers before any inner observer can retain
        # the caller credentials. Only the private Voice lane gets the typed value.
        scope["headers"] = [*sanitized_headers, (b"authorization", f"Bearer {key}".encode("latin-1"))]
        state = scope.setdefault("state", {})
        state["desktop_gateway_api_key"] = api_key
        if voice_lane:
            state["desktop_voice_credentials"] = DesktopVoiceCredentials(
                access_token=token, chatgpt_account_id=account_id, api_key=api_key, attestation=attestation
            )
        try:
            await self.app(scope, receive, send)
        finally:
            state.pop("desktop_gateway_api_key", None)
            if voice_lane:
                state.pop("desktop_voice_credentials", None)


def add_desktop_voice_credential_middleware(app: FastAPI) -> None:
    app.add_middleware(DesktopVoiceCredentialMiddleware)
