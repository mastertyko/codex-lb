"""Separate gateway admission from caller OAuth before ordinary proxy handling."""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import cast

from fastapi import FastAPI
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from app.core.auth.dependencies import validate_required_proxy_api_key_authorization
from app.core.auth.desktop_oauth import get_desktop_oauth
from app.core.clients.headers import CODEX_LB_KEY_HEADER
from app.core.errors import openai_error
from app.core.exceptions import ProxyAuthError
from app.core.middleware.path_rewrite import _canonicalize_backend_api_codex_path
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


_RETIRED_VOICE_PREFIX = "/backend-api/codex/desktop-voice"


def is_retired_desktop_voice_path(path: str) -> bool:
    path = _canonicalize_backend_api_codex_path(path)
    return path == _RETIRED_VOICE_PREFIX or path.startswith(_RETIRED_VOICE_PREFIX + "/")


class DesktopGatewayMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = _canonicalize_backend_api_codex_path(scope["path"])
        headers = scope.get("headers", [])
        if is_retired_desktop_voice_path(path):
            scope["headers"] = [
                (name, value) for name, value in headers if name.lower() not in _CALLER_IDENTITY_HEADERS
            ]
            scope["path"] = _RETIRED_VOICE_PREFIX + "/<redacted>"
            scope["raw_path"] = (_RETIRED_VOICE_PREFIX + "/%3Credacted%3E").encode("ascii")
            scope["query_string"] = b""
            response = JSONResponse(
                status_code=404,
                content=openai_error("desktop_voice_retired", "The Desktop Voice proxy is no longer available"),
            )
            if scope["type"] == "websocket":
                await WebSocket(scope, receive=receive, send=send).send_denial_response(response)
            else:
                await response(scope, receive, send)
            return
        if get_desktop_oauth(HTTPConnection(scope)) is not None:
            await self.app(scope, receive, send)
            return
        has_key = any(name.lower() == _KEY_HEADER for name, _ in headers)
        if not has_key:
            await self.app(scope, receive, send)
            return
        sanitized_headers = [(name, value) for name, value in headers if name.lower() not in _CALLER_IDENTITY_HEADERS]
        # Even a rejected credential must not remain in the server-owned headers.
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
                "ordinary",
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

        # Inner proxy code only receives the validated gateway identity.
        scope["headers"] = [*sanitized_headers, (b"authorization", f"Bearer {key}".encode("latin-1"))]
        state = scope.setdefault("state", {})
        state["desktop_gateway_api_key"] = api_key
        try:
            await self.app(scope, receive, send)
        finally:
            state.pop("desktop_gateway_api_key", None)


def add_desktop_gateway_middleware(app: FastAPI) -> None:
    app.add_middleware(DesktopGatewayMiddleware)
