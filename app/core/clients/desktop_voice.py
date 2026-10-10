"""One-shot native call creation for an authenticated Desktop owner."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Protocol, cast

import aiohttp

from app.core.clients.codex import (
    CodexClient,
    create_codex_session,
    release_codex_response,
    require_route_or_direct_egress_opt_in,
)
from app.core.clients.http import lease_http_session
from app.core.clients.proxy import MAX_SSE_EVENT_BYTES, CodexControlResponse, ProxyResponseError
from app.core.clients.proxy_websocket import _build_upstream_live_websocket_headers
from app.core.errors import openai_error
from app.core.upstream_proxy import ResolvedUpstreamRoute
from app.core.utils.shared_future import _await_task_deferring_cancellation

_NATIVE_CALL_URL = "https://chatgpt.com/backend-api/wham/realtime/calls"
_CLEANUP_TIMEOUT_SECONDS = 5.0


class _ResponseContent(Protocol):
    def iter_chunked(self, size: int, /) -> AsyncIterator[bytes]: ...


class _CallResponse(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    @property
    def content(self) -> _ResponseContent: ...


async def _read_call_response(response: _CallResponse) -> CodexControlResponse:
    if not 200 <= response.status < 300:
        status = response.status if 400 <= response.status <= 599 else 502
        raise ProxyResponseError(
            status, openai_error("desktop_voice_call_failed", "Desktop Voice call creation failed")
        )
    body = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        body.extend(chunk)
        if len(body) > MAX_SSE_EVENT_BYTES:
            raise ProxyResponseError(
                502, openai_error("desktop_voice_call_failed", "Desktop Voice response is too large")
            )
    return CodexControlResponse(response.status, bytes(body), dict(response.headers))


async def _close_routed_call(client: CodexClient, response: _CallResponse | None) -> None:
    try:
        if response is not None:
            await asyncio.wait_for(release_codex_response(response), timeout=_CLEANUP_TIMEOUT_SECONDS)
    except Exception:
        pass
    finally:
        try:
            await asyncio.wait_for(client.close(), timeout=_CLEANUP_TIMEOUT_SECONDS)
        except Exception:
            pass


async def create_desktop_voice_call(
    *,
    payload: bytes,
    headers: Mapping[str, str],
    query_params: Sequence[tuple[str, str]],
    access_token: str,
    account_id: str,
    route: ResolvedUpstreamRoute | None,
    allow_direct_egress: bool,
    timeout_seconds: float,
) -> CodexControlResponse:
    require_route_or_direct_egress_opt_in(
        route=route, allow_direct_egress=allow_direct_egress, operation="Desktop Voice call creation"
    )
    # This preserves the caller's installation/protocol context but replaces auth.
    forwarded = _build_upstream_live_websocket_headers(dict(headers), access_token, account_id)
    content_type = next((value for name, value in headers.items() if name.lower() == "content-type"), None)
    if content_type is not None:
        forwarded["content-type"] = content_type
    try:
        async with asyncio.timeout(timeout_seconds):
            if route is None:
                async with lease_http_session() as session:
                    async with session.post(
                        _NATIVE_CALL_URL,
                        data=payload,
                        params=list(query_params),
                        headers=forwarded,
                        allow_redirects=False,
                        timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                    ) as response:
                        return await _read_call_response(response)
            client = CodexClient(create_codex_session())
            response: _CallResponse | None = None
            try:
                response = await client.request(
                    "POST",
                    _NATIVE_CALL_URL,
                    route=route,
                    data=payload,
                    params=list(query_params),
                    headers=forwarded,
                    timeout=timeout_seconds,
                    allow_redirects=False,
                    buffer_response=False,
                )
                return await _read_call_response(cast(_CallResponse, response))
            finally:
                cleanup = asyncio.create_task(_close_routed_call(client, response))
                _, cancellation = await _await_task_deferring_cancellation(cleanup)
                if cancellation is not None:
                    raise cancellation
    except ProxyResponseError:
        raise
    except Exception:
        raise ProxyResponseError(
            502, openai_error("desktop_voice_call_failed", "Desktop Voice call creation failed")
        ) from None
