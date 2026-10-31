from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from app.core.clients.proxy_websocket import UpstreamWebSocket
from app.core.clock import REAL_CLOCK, REAL_SCHEDULER
from app.db.models import Account
from app.modules.proxy._service.support import _WebSocketUpstreamControl
from app.modules.proxy._service.websocket import retained
from app.modules.proxy._service.websocket.mixin import _WebSocketMixin
from app.modules.proxy.load_balancer import AccountLease

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def close_upstream(upstream):
    await upstream.close()


def entry(response: str = "resp_1", account_id: str = "account_1") -> retained.RetainedWebSocket:
    return retained.RetainedWebSocket(
        key=("key_1", "session_1", "conversation_1", response),
        account=Account(id=account_id),
        upstream=cast(UpstreamWebSocket, AsyncMock(spec=UpstreamWebSocket)),
        control=_WebSocketUpstreamControl(),
        lease=AccountLease("lease_" + response, account_id, "stream", 0.0, "key_1"),
    )


async def test_claim_is_single_owner_and_preserves_lease_until_closed():
    release = AsyncMock()
    registry = retained.RetainedWebSockets(release, close_upstream)
    socket = entry()
    assert registry.retain(socket)
    assert registry.take(socket.key, "other") is None
    assert registry.take(socket.key, socket.account.id) is socket
    assert registry.take(socket.key, socket.account.id) is None
    await asyncio.sleep(0)
    release.assert_not_awaited()
    socket.upstream.close.assert_not_awaited()
    await asyncio.gather(registry.close(socket), registry.close(socket))
    socket.upstream.close.assert_awaited_once()
    release.assert_awaited_once_with(socket.lease)
    await registry.close_all()
    assert not registry._tasks


async def test_expiry_closes_socket_and_settles_lease(monkeypatch):
    monkeypatch.setattr(retained, "RETAIN_SECONDS", 0.01)
    release = AsyncMock()
    registry = retained.RetainedWebSockets(release, close_upstream)
    socket = entry()
    assert registry.retain(socket)
    await asyncio.wait_for(asyncio.shield(socket.timer), timeout=1)
    assert not registry.entries
    assert registry.take(socket.key, socket.account.id) is None
    socket.upstream.close.assert_awaited_once()
    release.assert_awaited_once_with(socket.lease)
    await registry.close_all()


async def test_expired_socket_cannot_be_claimed_before_timer_runs():
    registry = retained.RetainedWebSockets(AsyncMock(), close_upstream)
    socket = entry()
    assert registry.retain(socket)
    socket.expires_at = asyncio.get_running_loop().time() - 1
    assert registry.take(socket.key, socket.account.id) is None
    await registry.close_all()
    socket.upstream.close.assert_awaited_once()


async def test_capacity_and_duplicate_refusal_leave_ownership_with_caller(monkeypatch):
    monkeypatch.setattr(retained, "MAX_RETAINED", 1)
    release = AsyncMock()
    registry = retained.RetainedWebSockets(release, close_upstream)
    owned, refused, duplicate = entry(), entry("resp_2"), entry()
    assert registry.retain(owned)
    assert not registry.retain(refused)
    assert not registry.retain(duplicate)
    await registry.close_all()
    owned.upstream.close.assert_awaited_once()
    refused.upstream.close.assert_not_awaited()
    duplicate.upstream.close.assert_not_awaited()
    release.assert_awaited_once_with(owned.lease)
    assert not registry.retain(entry("resp_after_shutdown"))


async def test_account_invalidation_closes_only_matching_owner():
    release = AsyncMock()
    registry = retained.RetainedWebSockets(release, close_upstream)
    first, second = entry(), entry("resp_2", "account_2")
    assert registry.retain(first)
    assert registry.retain(second)
    assert await registry.close_all(first.account.id) == 1
    first.upstream.close.assert_awaited_once()
    second.upstream.close.assert_not_awaited()
    assert registry.take(second.key, second.account.id) is second
    await registry.close(second)
    await registry.close_all()


async def test_shutdown_waits_for_already_expiring_socket(monkeypatch):
    monkeypatch.setattr(retained, "RETAIN_SECONDS", 0)
    release = AsyncMock()
    registry = retained.RetainedWebSockets(release, close_upstream)
    socket = entry()
    closing, finish = asyncio.Event(), asyncio.Event()

    async def close():
        closing.set()
        await finish.wait()

    socket.upstream.close.side_effect = close
    assert registry.retain(socket)
    await asyncio.wait_for(closing.wait(), 1)
    shutdown = asyncio.create_task(registry.close_all())
    await asyncio.sleep(0)
    assert not shutdown.done()
    finish.set()
    await asyncio.wait_for(shutdown, 1)
    socket.upstream.close.assert_awaited_once()
    release.assert_awaited_once_with(socket.lease)
    assert not registry._tasks


async def test_release_failure_does_not_skip_other_socket_cleanup():
    release = AsyncMock(side_effect=[RuntimeError("release failed"), None])
    registry = retained.RetainedWebSockets(release, close_upstream)
    first, second = entry(), entry("resp_2")
    assert registry.retain(first)
    assert registry.retain(second)
    with pytest.raises(RuntimeError, match="release failed"):
        await registry.close_all()
    assert release.await_count == 2
    first.upstream.close.assert_awaited_once()
    second.upstream.close.assert_awaited_once()
    assert not registry.entries
    assert not registry._tasks


async def test_stuck_transport_close_does_not_hold_lease_or_block_shutdown():
    release = AsyncMock()
    proxy = SimpleNamespace(_clock=REAL_CLOCK, _scheduler=REAL_SCHEDULER, _background_cleanup_tasks=set())

    async def bounded_close(upstream):
        await _WebSocketMixin._close_retained_websocket(proxy, upstream)

    registry = retained.RetainedWebSockets(release, bounded_close)
    socket = entry()
    started, finish = asyncio.Event(), asyncio.Event()

    async def stubborn_close():
        started.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            await finish.wait()

    socket.upstream.close.side_effect = stubborn_close
    assert registry.retain(socket)
    await asyncio.wait_for(registry.close_all(), timeout=2)
    assert started.is_set()
    release.assert_awaited_once_with(socket.lease)
    assert proxy._background_cleanup_tasks
    finish.set()
    await asyncio.gather(*proxy._background_cleanup_tasks)
    await asyncio.sleep(0)
    assert not proxy._background_cleanup_tasks
