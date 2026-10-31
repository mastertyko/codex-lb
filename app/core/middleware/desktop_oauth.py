"""Native Desktop credential boundary before ordinary proxy observers."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from app.core.auth.desktop_diagnostics import emit, trace_request
from app.core.auth.desktop_oauth import DesktopOAuthCredentials, authenticate_desktop_oauth
from app.core.clients.proxy import ProxyResponseError
from app.core.errors import openai_error
from app.core.exceptions import ProxyAuthError
from app.core.middleware.desktop_credentials import (
    _CALLER_IDENTITY_HEADERS,
    _KEY_HEADER,
    _MAX_ATTESTATION_BYTES,
    _is_native_attestation_envelope,
    _single_header,
    is_retired_desktop_voice_path,
)
from app.core.middleware.path_rewrite import _canonicalize_backend_api_codex_path


def _is_supported_native_route(path: str) -> bool:
    path = path.rstrip("/")
    if path == "/backend-api/codex/alpha/search":
        return True
    for prefix in ("/backend-api/codex", "/v1"):
        if path in {
            prefix + suffix
            for suffix in ("/responses", "/models", "/responses/compact", "/images/generations", "/images/edits")
        }:
            return True
    return False


class DesktopOAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        has_key = any(name.lower() == _KEY_HEADER for name, _ in headers)
        native = any(name.lower() == b"authorization" and value.count(b".") == 2 for name, value in headers)
        if has_key or not native or is_retired_desktop_voice_path(scope["path"]):
            await self.app(scope, receive, send)
            return
        with trace_request(scope["type"], scope.get("method")):
            await self._native_request(scope, receive, send, headers)

    async def _native_request(
        self, scope: Scope, receive: Receive, send: Send, headers: list[tuple[bytes, bytes]]
    ) -> None:
        path = _canonicalize_backend_api_codex_path(scope["path"])
        supported = _is_supported_native_route(path)
        route_kind = "unsupported_route"
        if supported:
            if path.rstrip("/").endswith("/responses/compact"):
                route_kind = "compact"
            elif path.rstrip("/").endswith("/models"):
                route_kind = "models"
            elif path.rstrip("/").endswith("/images/generations"):
                route_kind = "image_generation"
            elif path.rstrip("/").endswith("/images/edits"):
                route_kind = "image_edit"
            elif path.rstrip("/").endswith("/alpha/search"):
                route_kind = "search"
            else:
                route_kind = "responses"
        emit("request_route", reason=route_kind)
        sanitized = [(name, value) for name, value in headers if name.lower() not in _CALLER_IDENTITY_HEADERS]
        scope["headers"] = sanitized
        if not supported and any(
            path == prefix + "/realtime" or path.startswith(prefix + "/realtime/") or path.startswith(prefix + "/live/")
            for prefix in ("/backend-api/codex", "/v1")
        ):
            # Unsupported native realtime requests still carry private call context.
            scope["path"] = "/<redacted-native-realtime>"
            scope["raw_path"] = b"/%3Credacted-native-realtime%3E"
            scope["query_string"] = b""
        child = dict(scope)
        child["state"] = dict(scope.get("state", {}))
        try:
            if not supported:
                raise ProxyAuthError("Native Desktop route is unsupported")
            authorization = _single_header(headers, b"authorization")
            scheme, separator, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not separator or not token or any(c.isspace() for c in token):
                emit("auth_verification_failed", reason="unsupported_token")
                raise ProxyAuthError("Invalid native credential")
            accounts = [v for name, v in headers if name.lower() == b"chatgpt-account-id"]
            account = _single_header(headers, b"chatgpt-account-id") if accounts else None
            attestations = [v for name, v in headers if name.lower() == b"x-oai-attestation"]
            attestation = _single_header(headers, b"x-oai-attestation") if attestations else None
            if attestation is not None and (
                len(attestation) > _MAX_ATTESTATION_BYTES
                or any(ord(c) <= 32 or ord(c) >= 127 for c in attestation)
                or ("," in attestation and not _is_native_attestation_envelope(attestation))
            ):
                raise ProxyAuthError("Invalid native attestation")
            admission = await authenticate_desktop_oauth(DesktopOAuthCredentials(token, account, attestation))
        except (ProxyAuthError, ProxyResponseError) as exc:
            emit("auth_denied", status=exc.status_code, reason="auth")
            response = JSONResponse(
                status_code=exc.status_code,
                content=openai_error("desktop_oauth_denied", "Native Desktop access is unavailable"),
            )
            if scope["type"] == "websocket":
                await WebSocket(scope, receive=receive, send=send).send_denial_response(response)
            else:
                await response(scope, receive, send)
            return
        child["state"]["desktop_oauth"] = admission
        try:
            await self.app(child, receive, send)
        finally:
            child["state"].pop("desktop_oauth", None)


def add_desktop_oauth_middleware(app: FastAPI) -> None:
    app.add_middleware(DesktopOAuthMiddleware)
