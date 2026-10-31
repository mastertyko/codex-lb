"""Fixed-origin caller HTTP stream without pooled retries, archives or health writes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Protocol, cast

import aiohttp

from app.core.auth.desktop_diagnostics import emit
from app.core.clients.codex import CodexClient, create_codex_session, release_codex_response
from app.core.clients.proxy import MAX_SSE_EVENT_BYTES, ProxyResponseError, _build_upstream_headers, _find_sse_separator
from app.core.errors import openai_error
from app.core.openai.requests import ResponsesRequest
from app.core.upstream_proxy import ResolvedUpstreamRoute
from app.core.utils.shared_future import _await_task_deferring_cancellation

PREDICTION_BASE_URL = "https://chatgpt.com/backend-api"
PREDICTION_URL = PREDICTION_BASE_URL + "/codex/responses"


class _Body(Protocol):
    def iter_chunked(self, size: int) -> AsyncIterator[bytes]: ...


class _Response(Protocol):
    status: int
    headers: Mapping[str, str]
    content: _Body


async def _close(session: aiohttp.ClientSession, response: _Response | None) -> None:
    try:
        try:
            if response is not None:
                await asyncio.wait_for(release_codex_response(response), timeout=2)
        finally:
            await asyncio.wait_for(session.close(), timeout=2)
    except Exception:
        raise ProxyResponseError(
            502, openai_error("desktop_prediction_cleanup_failed", "Prediction cleanup failed")
        ) from None


async def stream_prediction(
    payload: ResponsesRequest,
    headers: Mapping[str, str],
    access_token: str,
    workspace_id: str,
    *,
    route: ResolvedUpstreamRoute | None,
    timeout_seconds: float,
) -> AsyncIterator[str]:
    session: aiohttp.ClientSession | None = None
    response: _Response | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            session = create_codex_session()
            upstream_headers = _build_upstream_headers(headers, access_token, workspace_id)
            kwargs = {
                "headers": upstream_headers,
                "json": payload.to_payload(),
                "allow_redirects": False,
            }
            if route is None:
                response = await session.post(
                    PREDICTION_URL, **kwargs, timeout=aiohttp.ClientTimeout(total=timeout_seconds)
                )
            else:
                response = cast(
                    _Response,
                    await CodexClient(session).request(
                        "POST",
                        PREDICTION_URL,
                        route=route.with_endpoint(route.endpoint, ()),
                        **kwargs,
                        timeout=timeout_seconds,
                        buffer_response=False,
                    ),
                )
            emit("upstream_status", status=response.status)
            if response.status != 200 or not response.headers.get("Content-Type", "").lower().startswith(
                "text/event-stream"
            ):
                raise ValueError("Unexpected Prediction response")
            buffer = bytearray()
            async for chunk in response.content.iter_chunked(16 * 1024):
                buffer.extend(chunk)
                while (separator := _find_sse_separator(buffer)) is not None:
                    position, size = separator
                    if position > MAX_SSE_EVENT_BYTES:
                        raise ValueError("Prediction event too large")
                    block = bytes(buffer[:position])
                    del buffer[: position + size]
                    yield block.decode("utf-8") + "\n\n"
                if len(buffer) > MAX_SSE_EVENT_BYTES:
                    raise ValueError("Prediction event too large")
            if buffer.strip():
                raise ValueError("Incomplete Prediction event")
    except Exception:
        raise ProxyResponseError(
            502, openai_error("desktop_prediction_upstream_failed", "Prediction upstream is unavailable")
        ) from None
    finally:
        if session is not None:
            task = asyncio.create_task(_close(session, response))
            _, cancellation = await _await_task_deferring_cancellation(task)
            if cancellation is not None:
                raise cancellation
