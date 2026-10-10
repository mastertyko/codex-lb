"""Authenticated Desktop Voice using one exact stored account, outside the pool."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Protocol, cast

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.core.auth import extract_id_token_claims
from app.core.auth.desktop_voice import (
    DesktopVoiceCredentials,
    DesktopVoicePrincipal,
    verify_desktop_voice_principal,
)
from app.core.clients.desktop_voice import create_desktop_voice_call
from app.core.clients.proxy import MAX_SSE_EVENT_BYTES, CodexControlResponse, ProxyResponseError
from app.core.clients.proxy_websocket import RealtimeWebSocketProtocol, normalize_realtime_call_id
from app.core.clock import clock_for, scheduler_for
from app.core.config.dashboard_overrides import with_dashboard_overrides
from app.core.config.settings import get_settings
from app.core.crypto import TokenEncryptor
from app.core.errors import openai_error
from app.core.upstream_proxy import ResolvedUpstreamRoute
from app.core.utils.shared_future import _await_task_deferring_cancellation
from app.db.models import Account, AccountStatus
from app.db.session import detach_session_objects
from app.modules.api_keys.service import ApiKeyData, ApiKeyInvalidError, ApiKeysService
from app.modules.proxy._service.support import (
    LiveWebSocketConnector,
    _CloseOnceLiveWebSocket,
    _relay_live_websocket,
    _safe_close_downstream,
    realtime_call_id_from_location,
)
from app.modules.proxy.load_balancer import LoadBalancer
from app.modules.proxy.repo_bundle import ProxyRepoFactory


class _DesktopVoiceProxy(Protocol):
    _repo_factory: ProxyRepoFactory
    _encryptor: TokenEncryptor
    _load_balancer: LoadBalancer
    _live_websocket_connector: LiveWebSocketConnector

    async def _resolve_upstream_route_for_account(
        self, account: Account, *, operation: str
    ) -> ResolvedUpstreamRoute | None: ...


@dataclass(frozen=True, slots=True)
class _StoredVoiceOwner:
    workspace_id: str = field(repr=False)
    access_token: str = field(repr=False)
    route: ResolvedUpstreamRoute | None = None


def _owner_error(code: str = "desktop_voice_owner_unavailable", *, status: int = 503) -> ProxyResponseError:
    return ProxyResponseError(status, openai_error(code, "Desktop Voice owner is unavailable"))


def _native_voice_headers(headers: Mapping[str, str], credentials: DesktopVoiceCredentials) -> dict[str, str]:
    forwarded = {name: value for name, value in headers.items() if name.lower() != "x-oai-attestation"}
    if credentials.attestation is not None:
        forwarded["x-oai-attestation"] = credentials.attestation
    return forwarded


def _check_owner(account: Account, principal: DesktopVoicePrincipal, api_key: ApiKeyData) -> None:
    if (
        account.delete_requested_at is not None
        or account.chatgpt_user_id != principal.user_id
        or account.chatgpt_account_id != principal.workspace_id
        or account.status not in (AccountStatus.ACTIVE, AccountStatus.PAUSED)
        or (api_key.account_assignment_scope_enabled and account.id not in api_key.assigned_account_ids)
    ):
        raise _owner_error()


def _stored_access_token(proxy: _DesktopVoiceProxy, account: Account, principal: DesktopVoicePrincipal) -> str:
    try:
        token = proxy._encryptor.decrypt(account.access_token_encrypted)
        if len(token) > 32 * 1024:
            raise ValueError
        claims = extract_id_token_claims(token)
        if (
            claims.auth is None
            or claims.auth.chatgpt_user_id != principal.user_id
            or claims.auth.chatgpt_account_id != principal.workspace_id
        ):
            raise ValueError
        expiry = float(claims.exp) if claims.exp is not None else 0.0
        if not math.isfinite(expiry) or expiry <= clock_for(proxy).time() + 30:
            raise _owner_error("desktop_voice_owner_token_expired")
    except ProxyResponseError:
        raise
    except Exception:
        raise _owner_error("desktop_voice_owner_token_invalid") from None
    return token


class _DesktopVoiceMixin:
    @asynccontextmanager
    async def _desktop_voice_owner(self, credentials: DesktopVoiceCredentials) -> AsyncIterator[_StoredVoiceOwner]:
        principal = await verify_desktop_voice_principal(credentials)
        proxy = cast(_DesktopVoiceProxy, self)
        async with proxy._repo_factory() as repos:
            owners = await repos.accounts.find_desktop_voice_owners(
                user_id=principal.user_id, workspace_id=principal.workspace_id
            )
            if len(owners) != 1:
                raise _owner_error("desktop_voice_owner_not_found", status=404)
            owner = owners[0]
            _check_owner(owner, principal, credentials.api_key)
            detach_session_objects(repos.accounts.session)
        lease = await proxy._load_balancer.acquire_account_lease(
            owner.id, kind="stream", api_key_id=credentials.api_key.id
        )
        if lease is None:
            raise _owner_error("desktop_voice_capacity_exceeded", status=429)
        try:
            route = await proxy._resolve_upstream_route_for_account(owner, operation="desktop_voice")
            # Recheck after all routing/admission awaits, before decrypting or using credentials.
            async with proxy._repo_factory() as repos:
                try:
                    fresh_key = await ApiKeysService(repos.api_keys).get_key_by_id(credentials.api_key.id)
                except ApiKeyInvalidError:
                    raise _owner_error("invalid_api_key", status=401) from None
                owners = await repos.accounts.find_desktop_voice_owners(
                    user_id=principal.user_id, workspace_id=principal.workspace_id
                )
                if len(owners) != 1 or owners[0].id != owner.id:
                    raise _owner_error()
                owner = owners[0]
                _check_owner(owner, principal, fresh_key)
                detach_session_objects(repos.accounts.session)
            yield _StoredVoiceOwner(principal.workspace_id, _stored_access_token(proxy, owner, principal), route)
        finally:
            task = scheduler_for(proxy).create_task(proxy._load_balancer.release_account_lease(lease))
            _, cancellation = await _await_task_deferring_cancellation(task)
            if cancellation is not None:
                raise cancellation

    async def create_desktop_voice_call(
        self,
        credentials: DesktopVoiceCredentials,
        *,
        payload: bytes,
        headers: Mapping[str, str],
        query_params: Sequence[tuple[str, str]],
    ) -> CodexControlResponse:
        settings = with_dashboard_overrides(get_settings())
        async with self._desktop_voice_owner(credentials) as owner:
            response = await create_desktop_voice_call(
                payload=payload,
                headers=_native_voice_headers(headers, credentials),
                query_params=query_params,
                access_token=owner.access_token,
                account_id=owner.workspace_id,
                route=owner.route,
                allow_direct_egress=owner.route is None,
                timeout_seconds=settings.proxy_request_budget_seconds,
            )
            if realtime_call_id_from_location(response.headers) is None:
                raise _owner_error("desktop_voice_invalid_call_response")
            return response

    async def proxy_desktop_voice_websocket(
        self,
        websocket: WebSocket,
        call_id: str,
        credentials: DesktopVoiceCredentials,
        *,
        protocol: RealtimeWebSocketProtocol,
        query_params: Sequence[tuple[str, str]],
    ) -> None:
        normalized = normalize_realtime_call_id(call_id)
        if normalized is None or any(key == "call_id" for key, _ in query_params):
            raise ProxyResponseError(400, openai_error("invalid_realtime_call_id", "Invalid realtime call id"))
        proxy = cast(_DesktopVoiceProxy, self)
        timeout = max(1.0, get_settings().upstream_connect_timeout_seconds)
        offered = tuple(cast(Sequence[str], websocket.scope.get("subprotocols", ())))
        async with self._desktop_voice_owner(credentials) as owner:
            peer: _CloseOnceLiveWebSocket | None = None
            try:
                upstream = await proxy._live_websocket_connector(
                    normalized,
                    _native_voice_headers(websocket.headers, credentials),
                    owner.access_token,
                    owner.workspace_id,
                    protocol=protocol,
                    route=owner.route,
                    allow_direct_egress=owner.route is None,
                    query_params=list(query_params),
                    subprotocols=offered,
                )
                peer = _CloseOnceLiveWebSocket(upstream)
                selected = peer.response_header("sec-websocket-protocol")
                if selected is not None and selected not in offered:
                    raise _owner_error("upstream_websocket_subprotocol_mismatch", status=502)
                await websocket.accept(subprotocol=selected)
                await _relay_live_websocket(
                    websocket, peer, max_message_bytes=MAX_SSE_EVENT_BYTES, close_timeout_seconds=timeout
                )
            except WebSocketDisconnect:
                pass
            except asyncio.CancelledError:
                await _safe_close_downstream(websocket, code=1011)
                raise
            except Exception:
                if websocket.application_state == WebSocketState.CONNECTED:
                    await _safe_close_downstream(websocket, code=1011)
                else:
                    raise
            finally:
                if peer is not None:
                    try:
                        await peer.close(timeout_seconds=timeout)
                    except Exception:
                        pass
