"""Shared authenticated Desktop caller identity boundary."""

from __future__ import annotations

import asyncio
import base64
import binascii
import math
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Protocol, cast

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.auth.desktop_diagnostics import emit
from app.core.clients.codex import CodexClient, create_codex_session, release_codex_response
from app.core.clients.proxy import ProxyResponseError
from app.core.errors import openai_error
from app.core.upstream_proxy import resolve_upstream_route
from app.core.usage.models import RateLimitPayload
from app.core.utils.shared_future import _await_task_deferring_cancellation
from app.db.session import get_background_session

_VERIFY_URL = "https://chatgpt.com/backend-api/wham/usage"
_VERIFY_TIMEOUT_SECONDS = 10.0
_VERIFY_MAX_BODY_BYTES = 64 * 1024
_VERIFY_CLEANUP_TIMEOUT_SECONDS = 2.0
_MAX_ACCESS_TOKEN_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class DesktopIdentityPrincipal:
    user_id: str = field(repr=False)
    workspace_id: str = field(repr=False)


class CallerBearer(Protocol):
    @property
    def access_token(self) -> str: ...

    @property
    def chatgpt_account_id(self) -> str | None: ...


class DesktopIdentityAuthError(ProxyResponseError):
    def __init__(self, *, unavailable: bool = False) -> None:
        super().__init__(
            503 if unavailable else 401,
            openai_error(
                "desktop_identity_unavailable" if unavailable else "desktop_identity_invalid",
                "Desktop identity verification is unavailable"
                if unavailable
                else "Desktop requires a valid authenticated user and workspace",
                error_type="server_error" if unavailable else "authentication_error",
            ),
        )


class _CallerAuthClaims(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    chatgpt_user_id: str = Field(min_length=1, max_length=256)
    chatgpt_account_id: str = Field(min_length=1, max_length=256)


class _CallerAccessClaims(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    auth: _CallerAuthClaims = Field(alias="https://api.openai.com/auth")
    exp: float


def parse_desktop_identity_principal(
    access_token: str,
    chatgpt_account_id: str | None = None,
) -> DesktopIdentityPrincipal:
    """Read a bounded selector, NOT proof of identity; verify the same bearer before use."""

    if len(access_token) > _MAX_ACCESS_TOKEN_BYTES:
        raise DesktopIdentityAuthError()
    parts = access_token.split(".")
    if len(parts) != 3 or not all(parts):
        raise DesktopIdentityAuthError()
    try:
        payload = base64.b64decode(parts[1] + "=" * (-len(parts[1]) % 4), altchars=b"-_", validate=True)
        claims = _CallerAccessClaims.model_validate_json(payload)
    except (ValueError, binascii.Error):
        claims = None
    if claims is None:
        raise DesktopIdentityAuthError()
    user_id = claims.auth.chatgpt_user_id
    workspace_id = claims.auth.chatgpt_account_id
    expiry = claims.exp
    if (
        user_id != user_id.strip()
        or workspace_id != workspace_id.strip()
        or (chatgpt_account_id is not None and chatgpt_account_id != workspace_id)
        or isinstance(expiry, bool)
        or not isinstance(expiry, (int, float))
        or not math.isfinite(expiry)
        or expiry <= time.time()
    ):
        raise DesktopIdentityAuthError()
    return DesktopIdentityPrincipal(user_id=user_id, workspace_id=workspace_id)


class _VerifiedRateLimit(RateLimitPayload):
    model_config = ConfigDict(extra="ignore", strict=True)

    allowed: bool | None = None


class _VerifiedUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    plan_type: str = Field(min_length=1, max_length=128)
    rate_limit: _VerifiedRateLimit


class _ResponseBody(Protocol):
    def iter_chunked(self, size: int) -> AsyncIterator[bytes]: ...


class _VerificationResponse(Protocol):
    status: int
    headers: Mapping[str, str]
    content: _ResponseBody


async def _check_response(response: _VerificationResponse) -> None:
    emit("auth_upstream_status", status=response.status)
    if response.status != 200:
        emit(
            "auth_verification_failed",
            status=response.status,
            reason="negative_verification" if response.status in (401, 403) else "upstream_status",
        )
        raise DesktopIdentityAuthError(unavailable=response.status not in (401, 403))
    if response.headers.get("Content-Type", "").partition(";")[0].strip().lower() != "application/json":
        emit("auth_verification_failed", reason="response_type")
        raise DesktopIdentityAuthError(unavailable=True)
    body = bytearray()
    async for chunk in response.content.iter_chunked(16 * 1024):
        if len(body) + len(chunk) > _VERIFY_MAX_BODY_BYTES:
            emit("auth_verification_failed", reason="response_size")
            raise DesktopIdentityAuthError(unavailable=True)
        body.extend(chunk)
    try:
        usage = _VerifiedUsage.model_validate_json(body)
    except ValidationError:
        usage = None
    if usage is None or not usage.plan_type.strip():
        emit("auth_verification_failed", reason="response_schema")
        raise DesktopIdentityAuthError(unavailable=True)
    limits = usage.rate_limit
    if limits.allowed is None and not any(
        window is not None and window.used_percent is not None
        for window in (limits.primary_window, limits.secondary_window)
    ):
        emit("auth_verification_failed", reason="response_schema")
        raise DesktopIdentityAuthError(unavailable=True)


async def _close_verification_resources(session: aiohttp.ClientSession, response: _VerificationResponse | None) -> bool:
    completed = True
    try:
        if response is not None:
            await asyncio.wait_for(release_codex_response(response), timeout=_VERIFY_CLEANUP_TIMEOUT_SECONDS)
    except Exception:
        completed = False
    finally:
        try:
            await asyncio.wait_for(session.close(), timeout=_VERIFY_CLEANUP_TIMEOUT_SECONDS)
        except Exception:
            completed = False
    return completed


async def verify_desktop_identity_principal(credentials: CallerBearer) -> DesktopIdentityPrincipal:
    try:
        principal = parse_desktop_identity_principal(credentials.access_token, credentials.chatgpt_account_id)
    except DesktopIdentityAuthError:
        emit("auth_verification_failed", reason="invalid_selector")
        raise
    emit("auth_verification_started")
    failure: DesktopIdentityAuthError | None = None
    resolving_route = True
    try:
        async with asyncio.timeout(_VERIFY_TIMEOUT_SECONDS):
            # No account is trusted yet: use the configured service egress policy.
            async with get_background_session() as db_session:
                route = await resolve_upstream_route(
                    db_session, account_id=None, operation="desktop_identity", scope="service"
                )
            resolving_route = False
            emit("auth_egress_ready", reason="direct" if route is None else "configured_egress")
            headers = {
                "Authorization": f"Bearer {credentials.access_token}",
                "chatgpt-account-id": principal.workspace_id,
                "Accept": "application/json",
            }
            session = create_codex_session()
            response: _VerificationResponse | None = None
            request_cancellation: asyncio.CancelledError | None = None
            try:
                if route is None:
                    response = await session.get(
                        _VERIFY_URL,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=_VERIFY_TIMEOUT_SECONDS),
                        allow_redirects=False,
                    )
                else:
                    # One endpoint, no retry/fallback. Explicit redirect policy selects
                    # the bounded aiohttp transport instead of the native buffered path.
                    response = cast(
                        _VerificationResponse,
                        await CodexClient(session).request(
                            "GET",
                            _VERIFY_URL,
                            route=route.with_endpoint(route.endpoint, ()),
                            headers=headers,
                            timeout=_VERIFY_TIMEOUT_SECONDS,
                            buffer_response=False,
                            allow_redirects=False,
                        ),
                    )
                await _check_response(response)
            except asyncio.CancelledError as exc:
                request_cancellation = exc
                raise
            finally:
                cleanup = asyncio.create_task(_close_verification_resources(session, response))
                completed, cancellation = await _await_task_deferring_cancellation(cleanup)
                if cancellation is not None:
                    raise cancellation
                if not completed and request_cancellation is None:
                    emit("auth_verification_failed", reason="cleanup")
                    raise DesktopIdentityAuthError(unavailable=True)
    except DesktopIdentityAuthError as exc:
        failure = exc
    except TimeoutError:
        emit("auth_verification_failed", reason="timeout")
        failure = DesktopIdentityAuthError(unavailable=True)
    except asyncio.CancelledError:
        emit("auth_verification_cancelled")
        raise
    except Exception:
        # Never retain/log the transport exception, URL, headers or response body.
        emit("auth_verification_failed", reason="route_failure" if resolving_route else "transport")
        failure = DesktopIdentityAuthError(unavailable=True)
    if failure is not None:
        raise failure from None
    # Recheck expiry after the bounded I/O; only now is the selector authenticated.
    try:
        verified = parse_desktop_identity_principal(credentials.access_token, principal.workspace_id)
    except DesktopIdentityAuthError:
        emit("auth_verification_failed", reason="invalid_selector")
        raise
    emit("auth_verified")
    return verified
