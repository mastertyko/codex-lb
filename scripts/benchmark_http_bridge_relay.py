#!/usr/bin/env python3
"""Deterministic benchmark for the real HTTP-bridge relay and stream consumer."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import math
import statistics
import time
from collections import deque
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from types import MethodType, SimpleNamespace
from typing import Any, cast

import anyio

from app.core.clients.proxy_websocket import UpstreamResponsesWebSocket, UpstreamWebSocketMessage
from app.core.utils.request_id import get_request_id
from app.core.utils.sse import parse_sse_data_json
from app.db.models import AccountStatus
from app.modules.proxy import service as proxy_service

_SAMPLE_COUNT = 21
_WARMUP_COUNT = 3
_REQUEST_COUNT = 8
_DELTA_COUNT = 64
_EVENTS_PER_REQUEST = _DELTA_COUNT + 3
_TOTAL_EVENT_COUNT = _REQUEST_COUNT * _EVENTS_PER_REQUEST
_EXPECTED_CORRECTNESS_DIGEST = "9d334ecc15ad699bfe811fc641c9eb7c3282a913eb80b200fb65dff5b8ff4955"
_REFERENCE_NS_PER_EVENT: dict[str, float] = {
    "relay_fast": 65_301.694,
    "relay_backlogged": 58_881.375,
}
_BLACKHOLE = 0


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    event_count: int
    total_bytes: int
    max_queue_depth: int


@dataclass(slots=True)
class PipelineFixture:
    service: proxy_service.ProxyService
    session: proxy_service._HTTPBridgeSession
    request_states: list[proxy_service._WebSocketRequestState]
    upstream: _FakeUpstream


@dataclass(frozen=True, slots=True)
class AsyncCase:
    name: str
    backlog_before_consume: bool


@dataclass(frozen=True, slots=True)
class Measurement:
    name: str
    median_ns_per_event: float
    p95_ns_per_event: float


async def _noop_method(_self: object, *args: object, **kwargs: object) -> None:
    return None


async def _false_method(_self: object, *args: object, **kwargs: object) -> bool:
    return False


class _FakeUpstream:
    def __init__(self, messages: Sequence[UpstreamWebSocketMessage]) -> None:
        self._messages = messages
        self._index = 0
        self.closed = False
        self.archive_count = 0
        self.archive_request_ids: list[str | None] = []
        self.close_count = 0

    async def send_text(self, _text: str) -> None:
        return None

    async def send_bytes(self, _data: bytes) -> None:
        return None

    async def receive(self) -> UpstreamWebSocketMessage:
        message = self._messages[self._index]
        self._index += 1
        return message

    async def close(self) -> None:
        self.close_count += 1
        self.closed = True

    def archive_received(self, _message: UpstreamWebSocketMessage) -> None:
        self.archive_count += 1
        self.archive_request_ids.append(get_request_id())


class _QueuedUpstream(_FakeUpstream):
    def __init__(self) -> None:
        super().__init__(())
        self._queue: asyncio.Queue[UpstreamWebSocketMessage] = asyncio.Queue()
        self.received_messages: list[UpstreamWebSocketMessage] = []
        self.receive_started = asyncio.Event()

    async def receive(self) -> UpstreamWebSocketMessage:
        self.receive_started.set()
        message = await self._queue.get()
        self.received_messages.append(message)
        return message

    def push(self, message: UpstreamWebSocketMessage) -> None:
        self._queue.put_nowait(message)


class _BlockingUpstream(_FakeUpstream):
    def __init__(self, messages: Sequence[UpstreamWebSocketMessage]) -> None:
        super().__init__(messages)
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()
        self.receive_cancelled = False

    async def receive(self) -> UpstreamWebSocketMessage:
        if self._index < len(self._messages):
            return await super().receive()
        self.blocked.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.receive_cancelled = True
            raise
        return UpstreamWebSocketMessage(kind="close", close_code=1000)


def _json_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _expected_sse_block(text: str) -> str:
    event_type = cast(str, json.loads(text)["type"])
    return f"event: {event_type}\ndata: {text}\n\n"


def _build_frame_texts(request_count: int, delta_count: int) -> tuple[str, ...]:
    texts: list[str] = []
    for request_index in range(request_count):
        response_id = f"resp_relay_bench_{request_index:03d}"
        texts.append(
            _json_text(
                {
                    "type": "response.created",
                    "response": {
                        "id": response_id,
                        "object": "response",
                        "status": "in_progress",
                        "output": [],
                    },
                }
            )
        )
        for delta_index in range(delta_count):
            texts.append(
                _json_text(
                    {
                        "type": "response.output_text.delta",
                        "response_id": response_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": f"token-{request_index:03d}-{delta_index:03d}",
                        "sequence_number": delta_index,
                    }
                )
            )
        texts.append(
            _json_text(
                {
                    "type": "response.output_text.done",
                    "response_id": response_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": f"done-{request_index:03d}",
                }
            )
        )
        texts.append(
            _json_text(
                {
                    "type": "response.completed",
                    "response": {
                        "id": response_id,
                        "object": "response",
                        "status": "completed",
                        "output": [],
                    },
                }
            )
        )
    return tuple(texts)


def _upstream_messages(
    frame_texts: Sequence[str],
    *,
    include_close: bool = True,
) -> tuple[UpstreamWebSocketMessage, ...]:
    messages = [UpstreamWebSocketMessage(kind="text", text=text) for text in frame_texts]
    if include_close:
        messages.append(UpstreamWebSocketMessage(kind="close", close_code=1000))
    return tuple(messages)


_FRAME_TEXTS = _build_frame_texts(_REQUEST_COUNT, _DELTA_COUNT)
_FRAME_MESSAGES = _upstream_messages(_FRAME_TEXTS)


def _patch_service(service: proxy_service.ProxyService) -> None:
    for method_name in (
        "_submit_http_bridge_request",
        "_detach_http_bridge_request",
        "_register_http_bridge_previous_response_id",
        "_finalize_websocket_request_state",
        "_fail_http_bridge_reader_and_maybe_retire",
    ):
        setattr(service, method_name, MethodType(_noop_method, service))
    for method_name in (
        "_retry_http_bridge_precreated_request",
        "_retire_http_bridge_after_drain_if_ready",
    ):
        setattr(service, method_name, MethodType(_false_method, service))


def _make_fixture(
    *,
    request_count: int = _REQUEST_COUNT,
    delta_count: int = _DELTA_COUNT,
    blocking_after_messages: int | None = None,
) -> PipelineFixture:
    service = proxy_service.ProxyService(cast(Any, nullcontext()))
    _patch_service(service)
    request_states = [
        proxy_service._WebSocketRequestState(
            request_id=f"req_relay_bench_{request_index:03d}",
            model="gpt-5.6-sol",
            service_tier=None,
            reasoning_effort=None,
            api_key_reservation=None,
            started_at=time.monotonic(),
            awaiting_response_created=True,
            event_queue=asyncio.Queue(),
            transport="http",
            request_text='{"type":"response.create"}',
            skip_request_log=True,
        )
        for request_index in range(request_count)
    ]
    if request_count == _REQUEST_COUNT and delta_count == _DELTA_COUNT and blocking_after_messages is None:
        messages = _FRAME_MESSAGES
    else:
        frame_texts = _build_frame_texts(request_count, delta_count)
        if blocking_after_messages is not None:
            frame_texts = frame_texts[:blocking_after_messages]
        messages = _upstream_messages(frame_texts, include_close=blocking_after_messages is None)
    upstream: _FakeUpstream
    if blocking_after_messages is None:
        upstream = _FakeUpstream(messages)
    else:
        upstream = _BlockingUpstream(messages)
    session = proxy_service._HTTPBridgeSession(
        key=proxy_service._HTTPBridgeSessionKey("session_header", "relay-benchmark", None),
        headers={"x-codex-session-id": "relay-benchmark"},
        affinity=proxy_service._AffinityPolicy(key="relay-benchmark"),
        request_model="gpt-5.6-sol",
        account=cast(
            Any,
            SimpleNamespace(id="acc-relay-benchmark", status=AccountStatus.ACTIVE),
        ),
        upstream=cast(UpstreamResponsesWebSocket, upstream),
        upstream_control=proxy_service._WebSocketUpstreamControl(),
        pending_requests=deque(request_states),
        pending_lock=anyio.Lock(fast_acquire=True),
        response_create_gate=asyncio.Semaphore(1),
        queued_request_count=request_count,
        last_used_at=1.0,
        idle_ttl_seconds=120.0,
    )
    return PipelineFixture(
        service=service,
        session=session,
        request_states=request_states,
        upstream=upstream,
    )


async def _consume_summary(
    service: proxy_service.ProxyService,
    session: proxy_service._HTTPBridgeSession,
    request_state: proxy_service._WebSocketRequestState,
) -> tuple[int, int]:
    event_count = 0
    total_bytes = 0
    async for block in service._stream_http_bridge_session_events(
        session,
        request_state=request_state,
        text_data=request_state.request_text or "{}",
        queue_limit=_REQUEST_COUNT,
        propagate_http_errors=False,
        downstream_turn_state=None,
    ):
        event_count += 1
        total_bytes += len(block)
    return event_count, total_bytes


async def _consume_blocks(
    service: proxy_service.ProxyService,
    session: proxy_service._HTTPBridgeSession,
    request_state: proxy_service._WebSocketRequestState,
) -> list[str]:
    return [
        block
        async for block in service._stream_http_bridge_session_events(
            session,
            request_state=request_state,
            text_data=request_state.request_text or "{}",
            queue_limit=_REQUEST_COUNT,
            propagate_http_errors=False,
            downstream_turn_state=None,
        )
    ]


async def _run_pipeline(fixture: PipelineFixture, *, backlog_before_consume: bool) -> PipelineSummary:
    relay_task = asyncio.create_task(
        fixture.service._relay_http_bridge_upstream_messages(fixture.session),
        name="benchmark-http-bridge-relay",
    )
    max_queue_depth = 0
    if backlog_before_consume:
        await relay_task
        max_queue_depth = max(
            cast(asyncio.Queue[str | None], state.event_queue).qsize() for state in fixture.request_states
        )
        consumer_tasks = [
            asyncio.create_task(
                _consume_summary(fixture.service, fixture.session, state),
                name=f"benchmark-http-consumer-{index}",
            )
            for index, state in enumerate(fixture.request_states)
        ]
    else:
        consumer_tasks = [
            asyncio.create_task(
                _consume_summary(fixture.service, fixture.session, state),
                name=f"benchmark-http-consumer-{index}",
            )
            for index, state in enumerate(fixture.request_states)
        ]
    summaries = await asyncio.gather(*consumer_tasks)
    await relay_task
    event_count = sum(summary[0] for summary in summaries)
    total_bytes = sum(summary[1] for summary in summaries)
    if fixture.session.pending_requests or fixture.session.queued_request_count != 0:
        raise RuntimeError("HTTP relay benchmark left pending requests")
    if any(cast(asyncio.Queue[str | None], state.event_queue).qsize() for state in fixture.request_states):
        raise RuntimeError("HTTP relay benchmark left queued events")
    return PipelineSummary(
        event_count=event_count,
        total_bytes=total_bytes,
        max_queue_depth=max_queue_depth,
    )


async def _collect_pipeline(fixture: PipelineFixture, *, backlog_before_consume: bool) -> tuple[list[list[str]], int]:
    relay_task = asyncio.create_task(fixture.service._relay_http_bridge_upstream_messages(fixture.session))
    max_queue_depth = 0
    if backlog_before_consume:
        await relay_task
        max_queue_depth = max(
            cast(asyncio.Queue[str | None], state.event_queue).qsize() for state in fixture.request_states
        )
    consumer_tasks = [
        asyncio.create_task(_consume_blocks(fixture.service, fixture.session, state))
        for state in fixture.request_states
    ]
    outputs = await asyncio.gather(*consumer_tasks)
    await relay_task
    return outputs, max_queue_depth


def _response_id(payload: dict[str, object]) -> str | None:
    direct = payload.get("response_id")
    if isinstance(direct, str):
        return direct
    response = payload.get("response")
    if isinstance(response, dict):
        nested = response.get("id")
        return nested if isinstance(nested, str) else None
    return None


def _validate_outputs(outputs: Sequence[Sequence[str]]) -> list[list[list[object]]]:
    expected_types = (
        ["response.created"]
        + ["response.output_text.delta"] * _DELTA_COUNT
        + [
            "response.output_text.done",
            "response.completed",
        ]
    )
    signature: list[list[list[object]]] = []
    if len(outputs) != _REQUEST_COUNT:
        raise RuntimeError(f"expected {_REQUEST_COUNT} output streams, got {len(outputs)}")
    for request_index, blocks in enumerate(outputs):
        expected_response_id = f"resp_relay_bench_{request_index:03d}"
        event_signature: list[list[object]] = []
        event_types: list[str] = []
        for block in blocks:
            payload = parse_sse_data_json(block)
            if payload is None:
                raise RuntimeError("relay emitted a non-JSON SSE block")
            event_type = payload.get("type")
            if not isinstance(event_type, str):
                raise RuntimeError("relay emitted an event without a type")
            response_id = _response_id(cast(dict[str, object], payload))
            if response_id != expected_response_id:
                raise RuntimeError(f"cross-request frame leak: expected {expected_response_id}, got {response_id}")
            event_types.append(event_type)
            event_signature.append([event_type, response_id, len(block), hashlib.sha256(block.encode()).hexdigest()])
        if event_types != expected_types:
            raise RuntimeError(f"relay order changed for {expected_response_id}: {event_types}")
        signature.append(event_signature)
    return signature


async def _verify_sentinel_contract() -> list[int]:
    fixture = _make_fixture()
    await fixture.service._relay_http_bridge_upstream_messages(fixture.session)
    depths: list[int] = []
    for state in fixture.request_states:
        queue = cast(asyncio.Queue[str | None], state.event_queue)
        if queue.maxsize != 0:
            raise RuntimeError("HTTP relay benchmark requires the production unbounded event queue")
        depths.append(queue.qsize())
        queued_items: list[str | None] = []
        while not queue.empty():
            queued_items.append(queue.get_nowait())
        if len(queued_items) != _EVENTS_PER_REQUEST + 1:
            raise RuntimeError("relay queue depth changed")
        if queued_items[-1] is not None or queued_items.count(None) != 1:
            raise RuntimeError("relay terminal sentinel contract changed")
        if any(item is None for item in queued_items[:-1]):
            raise RuntimeError("relay emitted an early terminal sentinel")
    return depths


async def _verify_cancellation_cleanup() -> dict[str, object]:
    fixture = _make_fixture(request_count=1, delta_count=2, blocking_after_messages=2)
    delattr(fixture.service, "_detach_http_bridge_request")
    delattr(fixture.service, "_retire_http_bridge_after_drain_if_ready")
    blocking_upstream = cast(_BlockingUpstream, fixture.upstream)
    request_state = fixture.request_states[0]
    before = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
    consumer_task = asyncio.create_task(
        _consume_blocks(fixture.service, fixture.session, request_state),
        name="benchmark-cancel-consumer",
    )
    relay_task = asyncio.create_task(
        fixture.service._relay_http_bridge_upstream_messages(fixture.session),
        name="benchmark-cancel-relay",
    )
    fixture.session.upstream_reader = relay_task
    await asyncio.wait_for(blocking_upstream.blocked.wait(), timeout=1.0)
    consumer_task.cancel()
    consumer_result = (await asyncio.gather(consumer_task, return_exceptions=True))[0]
    relay_result = (await asyncio.gather(relay_task, return_exceptions=True))[0]
    await asyncio.sleep(0)
    after = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
    leaked = [task for task in after - before if not task.done()]
    if not isinstance(consumer_result, asyncio.CancelledError):
        raise RuntimeError("stream consumer did not propagate cancellation")
    if not isinstance(relay_result, asyncio.CancelledError):
        raise RuntimeError("request detach did not cancel the upstream relay")
    if leaked:
        raise RuntimeError(f"relay cancellation leaked tasks: {leaked}")
    if (
        not fixture.session.closed
        or not blocking_upstream.closed
        or not blocking_upstream.receive_cancelled
        or blocking_upstream.close_count != 1
    ):
        raise RuntimeError("relay cancellation did not close task ownership cleanly")
    if (
        fixture.session.pending_requests
        or fixture.session.queued_request_count != 0
        or request_state.event_queue is not None
        or not request_state.draining_until_terminal
        or not fixture.session.upstream_control.reconnect_requested
        or not fixture.session.upstream_control.retire_after_drain
    ):
        raise RuntimeError("request detach left visible HTTP-bridge state")
    return {
        "consumer_cancelled": consumer_task.cancelled(),
        "relay_cancelled": relay_task.cancelled(),
        "receive_cancelled": blocking_upstream.receive_cancelled,
        "session_closed": fixture.session.closed,
        "upstream_close_count": blocking_upstream.close_count,
        "pending_count": len(fixture.session.pending_requests),
        "queued_request_count": fixture.session.queued_request_count,
        "event_queue_cleared": request_state.event_queue is None,
        "leaked_task_count": len(leaked),
    }


async def _short_receive_timeout(
    _self: object,
    *args: object,
    **kwargs: object,
) -> proxy_service._WebSocketReceiveTimeout:
    return proxy_service._WebSocketReceiveTimeout(
        timeout_seconds=0.001,
        error_code="benchmark_timeout",
        error_message="benchmark timeout",
    )


async def _verify_timeout_cleanup() -> dict[str, object]:
    fixture = _make_fixture(request_count=1, delta_count=0, blocking_after_messages=0)
    delattr(fixture.service, "_fail_http_bridge_reader_and_maybe_retire")
    setattr(
        fixture.service,
        "_next_websocket_receive_timeout",
        MethodType(_short_receive_timeout, fixture.service),
    )
    blocking_upstream = cast(_BlockingUpstream, fixture.upstream)
    before = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
    await asyncio.wait_for(
        fixture.service._relay_http_bridge_upstream_messages(fixture.session),
        timeout=1.0,
    )
    await asyncio.sleep(0)
    after = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
    leaked = [task for task in after - before if not task.done()]
    queue = cast(asyncio.Queue[str | None], fixture.request_states[0].event_queue)
    queued_items: list[str | None] = []
    while not queue.empty():
        queued_items.append(queue.get_nowait())
    failure_payload = parse_sse_data_json(cast(str, queued_items[0])) if queued_items else None
    if leaked:
        raise RuntimeError(f"relay timeout leaked tasks: {leaked}")
    if (
        len(queued_items) != 2
        or queued_items[-1] is not None
        or queued_items.count(None) != 1
        or failure_payload is None
        or failure_payload.get("type") != "response.failed"
    ):
        raise RuntimeError("relay timeout terminal event contract changed")
    if (
        not fixture.session.closed
        or fixture.session.pending_requests
        or fixture.session.queued_request_count != 0
        or not blocking_upstream.closed
        or not blocking_upstream.receive_cancelled
        or blocking_upstream.close_count != 1
    ):
        raise RuntimeError("relay timeout did not clean pending ownership")
    return {
        "terminal_event_type": failure_payload["type"],
        "terminal_sentinel_count": queued_items.count(None),
        "receive_cancelled": blocking_upstream.receive_cancelled,
        "session_closed": fixture.session.closed,
        "upstream_close_count": blocking_upstream.close_count,
        "pending_count": len(fixture.session.pending_requests),
        "queued_request_count": fixture.session.queued_request_count,
        "leaked_task_count": len(leaked),
    }


async def _wait_for_length(items: Sequence[object], expected: int) -> None:
    async with asyncio.timeout(1.0):
        while len(items) < expected:
            await asyncio.sleep(0)


async def _wait_for_lock(lock: anyio.Lock, started: asyncio.Event) -> None:
    started.set()
    async with lock:
        return None


async def _verify_contended_pending_lock_contract() -> dict[str, object]:
    fixture = _make_fixture(request_count=2, delta_count=1)
    first_state, second_state = fixture.request_states
    first_state.archive_request_id = "archive-http-contended-0"
    second_state.archive_request_id = "archive-http-contended-1"
    fixture.session.pending_requests = deque([first_state])
    fixture.session.queued_request_count = 1
    upstream = _QueuedUpstream()
    fixture.upstream = upstream
    fixture.session.upstream = cast(UpstreamResponsesWebSocket, upstream)
    response_ids = ("resp-http-contended-0", "resp-http-contended-1")
    frame_texts = (
        _json_text(
            {
                "type": "response.created",
                "response": {"id": response_ids[0], "status": "in_progress", "output": []},
            }
        ),
        _json_text(
            {
                "type": "response.created",
                "response": {"id": response_ids[1], "status": "in_progress", "output": []},
            }
        ),
        _json_text(
            {
                "type": "response.output_text.delta",
                "response_id": response_ids[1],
                "delta": "second",
                "sequence_number": 0,
            }
        ),
        _json_text(
            {
                "type": "response.output_text.delta",
                "response_id": response_ids[0],
                "delta": "first",
                "sequence_number": 0,
            }
        ),
        _json_text(
            {
                "type": "response.output_text.done",
                "response_id": response_ids[1],
                "text": "second",
                "sequence_number": 1,
            }
        ),
        _json_text(
            {
                "type": "response.output_text.done",
                "response_id": response_ids[0],
                "text": "first",
                "sequence_number": 1,
            }
        ),
        _json_text(
            {
                "type": "response.completed",
                "response": {"id": response_ids[1], "status": "completed", "output": []},
            }
        ),
        _json_text(
            {
                "type": "response.completed",
                "response": {"id": response_ids[0], "status": "completed", "output": []},
            }
        ),
    )
    relay_task = asyncio.create_task(
        fixture.service._relay_http_bridge_upstream_messages(fixture.session),
        name="benchmark-contended-http-relay",
    )
    cancelled_waiter: asyncio.Task[None] | None = None
    try:
        async with asyncio.timeout(1.0):
            await upstream.receive_started.wait()
        async with fixture.session.pending_lock:
            fixture.session.pending_requests.append(second_state)
            fixture.session.queued_request_count += 1
            waiter_started = asyncio.Event()
            cancelled_waiter = asyncio.create_task(
                _wait_for_lock(fixture.session.pending_lock, waiter_started),
                name="benchmark-cancelled-http-pending-waiter",
            )
            await waiter_started.wait()
            await asyncio.sleep(0)
            upstream.push(UpstreamWebSocketMessage(kind="text", text=frame_texts[0]))
            await _wait_for_length(upstream.received_messages, 1)
            await asyncio.sleep(0)
            cancelled_waiter.cancel()
            await asyncio.gather(cancelled_waiter, return_exceptions=True)
        await _wait_for_length(upstream.archive_request_ids, 1)

        for text in frame_texts[1:]:
            upstream.push(UpstreamWebSocketMessage(kind="text", text=text))
        upstream.push(UpstreamWebSocketMessage(kind="close", close_code=1000))
        async with asyncio.timeout(1.0):
            await relay_task
    finally:
        for task in (cancelled_waiter, relay_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (cancelled_waiter, relay_task) if task is not None),
            return_exceptions=True,
        )

    outputs = await asyncio.gather(
        *(_consume_blocks(fixture.service, fixture.session, state) for state in fixture.request_states)
    )
    expected_outputs = [
        [_expected_sse_block(frame_texts[index]) for index in (0, 3, 5, 7)],
        [_expected_sse_block(frame_texts[index]) for index in (1, 2, 4, 6)],
    ]
    expected_archive_ids = [
        "archive-http-contended-0",
        "archive-http-contended-1",
        "archive-http-contended-1",
        "archive-http-contended-0",
        "archive-http-contended-1",
        "archive-http-contended-0",
        "archive-http-contended-1",
        "archive-http-contended-0",
        None,
    ]
    if outputs != expected_outputs:
        raise RuntimeError("pending-lock contention changed HTTP bridge frame routing or order")
    if upstream.archive_request_ids != expected_archive_ids:
        raise RuntimeError("pending-lock contention changed HTTP bridge archive attribution")
    if cancelled_waiter is None or not cancelled_waiter.cancelled():
        raise RuntimeError("cancelled HTTP bridge lock waiter acquired the contended lock")
    if fixture.session.pending_requests or fixture.session.queued_request_count != 0:
        raise RuntimeError("contended HTTP bridge relay left pending request ownership")
    return {
        "archive_request_ids": upstream.archive_request_ids,
        "cancelled_waiter": cancelled_waiter.cancelled(),
        "event_counts": [len(output) for output in outputs],
        "pending_count": len(fixture.session.pending_requests),
        "queued_request_count": fixture.session.queued_request_count,
    }


async def _verify_correctness() -> str:
    fast_outputs, fast_depth = await _collect_pipeline(_make_fixture(), backlog_before_consume=False)
    backlogged_outputs, backlog_depth = await _collect_pipeline(_make_fixture(), backlog_before_consume=True)
    if fast_outputs != backlogged_outputs:
        raise RuntimeError("slow consumer changed relay output")
    signature = _validate_outputs(fast_outputs)
    sentinel_depths = await _verify_sentinel_contract()
    if fast_depth != 0 or backlog_depth != _EVENTS_PER_REQUEST + 1:
        raise RuntimeError("slow-consumer queue-depth contract changed")
    cancellation = await _verify_cancellation_cleanup()
    timeout = await _verify_timeout_cleanup()
    payload = {
        "events": signature,
        "fast_queue_depth": fast_depth,
        "backlog_queue_depth": backlog_depth,
        "sentinel_queue_depths": sentinel_depths,
        "cancellation": cancellation,
        "timeout": timeout,
        "contended_pending_lock": await _verify_contended_pending_lock_contract(),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != _EXPECTED_CORRECTNESS_DIGEST:
        raise RuntimeError(
            f"relay benchmark correctness digest changed: expected {_EXPECTED_CORRECTNESS_DIGEST}, got {digest}"
        )
    return digest


def _percentile_95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _consume_blackhole(summary: PipelineSummary) -> None:
    global _BLACKHOLE
    _BLACKHOLE ^= summary.event_count ^ summary.total_bytes ^ summary.max_queue_depth


async def _measure(case: AsyncCase) -> Measurement:
    for _ in range(_WARMUP_COUNT):
        summary = await _run_pipeline(
            _make_fixture(),
            backlog_before_consume=case.backlog_before_consume,
        )
        _consume_blackhole(summary)
    elapsed_samples: list[int] = []
    for _ in range(_SAMPLE_COUNT):
        fixture = _make_fixture()
        gc.collect()
        started = time.perf_counter_ns()
        summary = await _run_pipeline(
            fixture,
            backlog_before_consume=case.backlog_before_consume,
        )
        elapsed_samples.append(time.perf_counter_ns() - started)
        _consume_blackhole(summary)
        if summary.event_count != _TOTAL_EVENT_COUNT:
            raise RuntimeError("relay benchmark lost events")
    return Measurement(
        name=case.name,
        median_ns_per_event=statistics.median(elapsed_samples) / _TOTAL_EVENT_COUNT,
        p95_ns_per_event=_percentile_95(elapsed_samples) / _TOTAL_EVENT_COUNT,
    )


def _relay_score(measurements: Sequence[Measurement]) -> float:
    ratios = [
        _REFERENCE_NS_PER_EVENT[measurement.name] / measurement.median_ns_per_event for measurement in measurements
    ]
    return math.exp(sum(math.log(ratio) for ratio in ratios) / len(ratios)) * 1_000.0


async def main() -> None:
    correctness_digest = await _verify_correctness()
    cases = (
        AsyncCase("relay_fast", backlog_before_consume=False),
        AsyncCase("relay_backlogged", backlog_before_consume=True),
    )
    measurements = [await _measure(case) for case in cases]
    print(f"ASI correctness_digest={correctness_digest}")
    print(f"ASI blackhole={_BLACKHOLE}")
    print(f"ASI sample_count={_SAMPLE_COUNT}")
    print(f"ASI request_count={_REQUEST_COUNT}")
    print(f"ASI delta_count={_DELTA_COUNT}")
    print(f"ASI total_event_count={_TOTAL_EVENT_COUNT}")
    print(f"METRIC http_bridge_relay_score={_relay_score(measurements):.6f}")
    for measurement in measurements:
        print(f"METRIC {measurement.name}_ns_per_event={measurement.median_ns_per_event:.3f}")
        print(f"METRIC {measurement.name}_p95_ns_per_event={measurement.p95_ns_per_event:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
