"""Short-lived ownership of completed, authenticated upstream WebSockets."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core.clients.proxy_websocket import UpstreamWebSocket
from app.db.models import Account
from app.modules.proxy.load_balancer import AccountLease

if TYPE_CHECKING:
    from app.modules.proxy._service.support import _WebSocketUpstreamControl

logger = logging.getLogger(__name__)
RETAIN_SECONDS = 20.0
MAX_RETAINED = 32
RetainedKey = tuple[str, str, str | None, str]


@dataclass(slots=True)
class RetainedWebSocket:
    key: RetainedKey
    account: Account
    upstream: UpstreamWebSocket
    control: _WebSocketUpstreamControl
    lease: AccountLease | None
    security_work_authorized: bool = False
    expires_at: float = 0.0
    timer: asyncio.Task[None] | None = None
    close_task: asyncio.Task[None] | None = None


class RetainedWebSockets:
    """All registry transfers are synchronous and atomic on the service loop."""

    def __init__(
        self,
        release: Callable[[AccountLease | None], Awaitable[None]],
        close_upstream: Callable[[UpstreamWebSocket], Awaitable[None]],
    ) -> None:
        self.entries: dict[RetainedKey, RetainedWebSocket] = {}
        self._release = release
        self._close_upstream = close_upstream
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    def _track(self, coroutine: Coroutine[Any, Any, None], name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)

        def done(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(done)
        return task

    def retain(self, entry: RetainedWebSocket) -> bool:
        if self._closed or entry.key in self.entries or len(self.entries) >= MAX_RETAINED:
            return False
        entry.expires_at = asyncio.get_running_loop().time() + RETAIN_SECONDS
        self.entries[entry.key] = entry
        entry.timer = self._track(self._expire(entry), "websocket-retained-expiry")
        logger.info("websocket_retained event=parked connection_id=%s", entry.control.diagnostic_connection_id)
        return True

    def take(self, key: RetainedKey, account_id: str) -> RetainedWebSocket | None:
        entry = self.entries.get(key)
        if entry is None or entry.account.id != account_id:
            return None
        if asyncio.get_running_loop().time() >= entry.expires_at:
            # The timer owns disposal; do not resurrect expired entries if its
            # scheduled callback has not run yet.
            return None
        self.entries.pop(key)
        if entry.timer is not None:
            entry.timer.cancel()
        logger.info("websocket_retained event=claimed connection_id=%s", entry.control.diagnostic_connection_id)
        return entry

    async def _expire(self, entry: RetainedWebSocket) -> None:
        await asyncio.sleep(max(0.0, entry.expires_at - asyncio.get_running_loop().time()))
        if self.entries.get(entry.key) is entry:
            self.entries.pop(entry.key)
            await self.close(entry)

    async def close(self, entry: RetainedWebSocket) -> None:
        if entry.close_task is None:
            entry.close_task = self._track(self._dispose(entry), "websocket-retained-close")
        await asyncio.shield(entry.close_task)

    async def _dispose(self, entry: RetainedWebSocket) -> None:
        try:
            await self._close_upstream(entry.upstream)
        except Exception:
            logger.warning("websocket_retained event=close_failed")
        finally:
            await self._release(entry.lease)
            logger.info("websocket_retained event=closed connection_id=%s", entry.control.diagnostic_connection_id)

    async def close_all(self, account_id: str | None = None) -> int:
        if account_id is None:
            self._closed = True
        entries = [entry for entry in self.entries.values() if account_id is None or entry.account.id == account_id]
        for entry in entries:
            self.entries.pop(entry.key)
            if entry.timer is not None:
                entry.timer.cancel()
        results = await asyncio.gather(*(self.close(entry) for entry in entries), return_exceptions=True)
        if account_id is None:
            # Includes disposal already started by an expiry callback.
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self._tasks)), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return len(entries)
