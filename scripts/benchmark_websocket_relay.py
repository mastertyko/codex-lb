#!/usr/bin/env python3
"""Deterministic benchmark for the real direct-WebSocket relay hot path."""

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
from app.db.models import AccountStatus
from app.modules.proxy import service as proxy_service
from app.modules.proxy._service.websocket.mixin import _websocket_archive_request_id_for_message

_SAMPLE_COUNT = 21
_WARMUP_COUNT = 3
_REQUEST_COUNT = 8
_DELTA_COUNT = 64
_EVENTS_PER_REQUEST = _DELTA_COUNT + 3
_TOTAL_EVENT_COUNT = _REQUEST_COUNT * _EVENTS_PER_REQUEST
_EXPECTED_CORRECTNESS_DIGEST = "09972dedab80ed986cde57b14137026ab0c6eee91588dcc8d0cf815fe8c3b7b1"
_REFERENCE_NS_PER_EVENT = 77_331.312
_BLACKHOLE = 0


@dataclass(frozen=True, slots=True)
class RelaySummary:
    event_count: int
    total_bytes: int
    archive_count: int


@dataclass(slots=True)
class RelayFixture:
    service: proxy_service.ProxyService
    websocket: _FakeWebSocket
    upstream: _FakeUpstream
    pending_requests: deque[proxy_service._WebSocketRequestState]
    pending_lock: anyio.Lock
    client_send_lock: anyio.Lock
    response_create_gate: asyncio.Semaphore
    upstream_control: proxy_service._WebSocketUpstreamControl
    account: Any


@dataclass(frozen=True, slots=True)
class Measurement:
    median_ns_per_event: float
    p95_ns_per_event: float


async def _noop_method(_self: object, *args: object, **kwargs: object) -> None:
    return None


class _FakeUpstream:
    def __init__(self, messages: Sequence[UpstreamWebSocketMessage]) -> None:
        self._messages = messages
        self._index = 0
        self.closed = False
        self.archived_request_ids: list[str | None] = []

    async def receive(self) -> UpstreamWebSocketMessage:
        message = self._messages[self._index]
        self._index += 1
        return message

    async def close(self) -> None:
        self.closed = True

    def archive_received(self, _message: UpstreamWebSocketMessage) -> None:
        self.archived_request_ids.append(get_request_id())


class _QueuedUpstream(_FakeUpstream):
    def __init__(self) -> None:
        super().__init__(())
        self._queue: asyncio.Queue[UpstreamWebSocketMessage] = asyncio.Queue()

    async def receive(self) -> UpstreamWebSocketMessage:
        return await self._queue.get()

    def push(self, message: UpstreamWebSocketMessage) -> None:
        self._queue.put_nowait(message)


class _SignalingUpstream(_FakeUpstream):
    def __init__(self, messages: Sequence[UpstreamWebSocketMessage]) -> None:
        super().__init__(messages)
        self.first_receive_started = asyncio.Event()

    async def receive(self) -> UpstreamWebSocketMessage:
        if self._index == 0:
            self.first_receive_started.set()
        return await super().receive()


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent_text: list[str] = []
        self.sent_bytes: list[bytes] = []
        self.closed = False

    async def send_text(self, text: str) -> None:
        self.sent_text.append(text)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)

    async def close(self) -> None:
        self.closed = True


def _json_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _build_frame_texts(request_count: int, delta_count: int) -> tuple[str, ...]:
    texts: list[str] = []
    response_ids = [f"resp_ws_relay_bench_{index:03d}" for index in range(request_count)]
    for response_id in response_ids:
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
        for request_index, response_id in enumerate(response_ids):
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
    for request_index, response_id in enumerate(response_ids):
        texts.append(
            _json_text(
                {
                    "type": "response.output_text.done",
                    "response_id": response_id,
                    "output_index": 0,
                    "content_index": 0,
                    "text": f"done-{request_index:03d}",
                    "sequence_number": delta_count,
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


_FRAME_TEXTS = _build_frame_texts(_REQUEST_COUNT, _DELTA_COUNT)
_FRAME_MESSAGES = tuple(
    [UpstreamWebSocketMessage(kind="text", text=text) for text in _FRAME_TEXTS]
    + [UpstreamWebSocketMessage(kind="close", close_code=1000)]
)


def _patch_service(service: proxy_service.ProxyService) -> None:
    for method_name in (
        "_next_websocket_receive_timeout",
        "_finalize_websocket_request_state",
        "_fail_pending_websocket_requests",
    ):
        setattr(service, method_name, MethodType(_noop_method, service))


def _make_fixture() -> RelayFixture:
    service = proxy_service.ProxyService(cast(Any, nullcontext()))
    _patch_service(service)
    request_states = deque(
        proxy_service._WebSocketRequestState(
            request_id=f"req_ws_relay_bench_{request_index:03d}",
            model="gpt-5.6-sol",
            service_tier=None,
            reasoning_effort=None,
            api_key_reservation=None,
            started_at=time.monotonic(),
            archive_request_id=f"archive_ws_relay_bench_{request_index:03d}",
            awaiting_response_created=True,
            request_text='{"type":"response.create"}',
            skip_request_log=True,
        )
        for request_index in range(_REQUEST_COUNT)
    )
    return RelayFixture(
        service=service,
        websocket=_FakeWebSocket(),
        upstream=_FakeUpstream(_FRAME_MESSAGES),
        pending_requests=request_states,
        pending_lock=anyio.Lock(fast_acquire=True),
        client_send_lock=anyio.Lock(fast_acquire=True),
        response_create_gate=asyncio.Semaphore(1),
        upstream_control=proxy_service._WebSocketUpstreamControl(),
        account=SimpleNamespace(
            id="acc-ws-relay-benchmark",
            status=AccountStatus.ACTIVE,
            security_work_authorized=True,
        ),
    )


async def _run_relay(fixture: RelayFixture) -> RelaySummary:
    await fixture.service._relay_upstream_websocket_messages(
        cast(Any, fixture.websocket),
        cast(UpstreamResponsesWebSocket, fixture.upstream),
        account=fixture.account,
        account_id_value=fixture.account.id,
        pending_requests=fixture.pending_requests,
        pending_lock=fixture.pending_lock,
        client_send_lock=fixture.client_send_lock,
        api_key=None,
        upstream_control=fixture.upstream_control,
        response_create_gate=fixture.response_create_gate,
        proxy_request_budget_seconds=600.0,
        stream_idle_timeout_seconds=600.0,
        downstream_activity=proxy_service._DownstreamWebSocketActivity(),
        continuity_state=None,
    )
    if fixture.pending_requests:
        raise RuntimeError("WebSocket relay benchmark left pending requests")
    if fixture.websocket.sent_bytes:
        raise RuntimeError("text relay emitted unexpected binary frames")
    return RelaySummary(
        event_count=len(fixture.websocket.sent_text),
        total_bytes=sum(len(text) for text in fixture.websocket.sent_text),
        archive_count=len(fixture.upstream.archived_request_ids),
    )


def _response_id(payload: dict[str, object]) -> str | None:
    direct = payload.get("response_id")
    if isinstance(direct, str):
        return direct
    response = payload.get("response")
    if not isinstance(response, dict):
        return None
    nested = response.get("id")
    return nested if isinstance(nested, str) else None


def _verify_malformed_created_is_unattributed() -> bool:
    pending_requests = deque(
        [
            proxy_service._WebSocketRequestState(
                request_id="req-malformed-created",
                model="gpt-5.6-sol",
                service_tier=None,
                reasoning_effort=None,
                api_key_reservation=None,
                started_at=time.monotonic(),
                archive_request_id="archive-malformed-created",
                awaiting_response_created=True,
            )
        ]
    )
    message = UpstreamWebSocketMessage(
        kind="text",
        text=_json_text(
            {
                "type": "response.created",
                "response": {"object": "response", "status": "in_progress", "output": []},
            }
        ),
    )
    archive_request_id = _websocket_archive_request_id_for_message(
        message,
        pending_requests=pending_requests,
    )
    if archive_request_id is not None:
        raise RuntimeError("malformed response.created claimed a pending archive request")
    return True


async def _wait_for_length(items: Sequence[object], expected: int) -> None:
    async with asyncio.timeout(1.0):
        while len(items) < expected:
            await asyncio.sleep(0)


async def _wait_for_lock(lock: anyio.Lock, started: asyncio.Event) -> None:
    started.set()
    async with lock:
        return None


async def _verify_contended_lock_contract() -> dict[str, object]:
    service = proxy_service.ProxyService(cast(Any, nullcontext()))
    _patch_service(service)
    request_states = [
        proxy_service._WebSocketRequestState(
            request_id=f"req-ws-contended-{index}",
            model="gpt-5.6-sol",
            service_tier=None,
            reasoning_effort=None,
            api_key_reservation=None,
            started_at=time.monotonic(),
            archive_request_id=f"archive-ws-contended-{index}",
            awaiting_response_created=True,
            request_text='{"type":"response.create"}',
            skip_request_log=True,
        )
        for index in range(2)
    ]
    response_ids = [f"resp-ws-contended-{index}" for index in range(2)]
    frame_texts = [
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
    ]
    upstream = _QueuedUpstream()
    fixture = RelayFixture(
        service=service,
        websocket=_FakeWebSocket(),
        upstream=upstream,
        pending_requests=deque([request_states[0]]),
        pending_lock=anyio.Lock(fast_acquire=True),
        client_send_lock=anyio.Lock(fast_acquire=True),
        response_create_gate=asyncio.Semaphore(1),
        upstream_control=proxy_service._WebSocketUpstreamControl(),
        account=SimpleNamespace(
            id="acc-ws-contended",
            status=AccountStatus.ACTIVE,
            security_work_authorized=True,
        ),
    )
    relay_task = asyncio.create_task(_run_relay(fixture), name="benchmark-contended-ws-relay")
    pending_waiter: asyncio.Task[None] | None = None
    send_waiter: asyncio.Task[None] | None = None
    try:
        async with fixture.pending_lock:
            fixture.pending_requests.append(request_states[1])
            pending_wait_started = asyncio.Event()
            pending_waiter = asyncio.create_task(
                _wait_for_lock(fixture.pending_lock, pending_wait_started),
                name="benchmark-cancelled-pending-lock-waiter",
            )
            await pending_wait_started.wait()
            await asyncio.sleep(0)
            upstream.push(UpstreamWebSocketMessage(kind="text", text=frame_texts[0]))
            await _wait_for_length(upstream.archived_request_ids, 1)
            pending_waiter.cancel()
            await asyncio.gather(pending_waiter, return_exceptions=True)
        await _wait_for_length(fixture.websocket.sent_text, 1)

        async with fixture.client_send_lock:
            send_wait_started = asyncio.Event()
            send_waiter = asyncio.create_task(
                _wait_for_lock(fixture.client_send_lock, send_wait_started),
                name="benchmark-cancelled-send-lock-waiter",
            )
            await send_wait_started.wait()
            await asyncio.sleep(0)
            upstream.push(UpstreamWebSocketMessage(kind="text", text=frame_texts[1]))
            await _wait_for_length(upstream.archived_request_ids, 2)
            await asyncio.sleep(0)
            send_waiter.cancel()
            await asyncio.gather(send_waiter, return_exceptions=True)
        await _wait_for_length(fixture.websocket.sent_text, 2)

        for text in frame_texts[2:]:
            upstream.push(UpstreamWebSocketMessage(kind="text", text=text))
        upstream.push(UpstreamWebSocketMessage(kind="close", close_code=1000))
        async with asyncio.timeout(1.0):
            summary = await relay_task
    finally:
        for task in (pending_waiter, send_waiter, relay_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (pending_waiter, send_waiter, relay_task) if task is not None),
            return_exceptions=True,
        )

    expected_archive_ids = [
        "archive-ws-contended-0",
        "archive-ws-contended-1",
        "archive-ws-contended-1",
        "archive-ws-contended-0",
        "archive-ws-contended-1",
        "archive-ws-contended-0",
        None,
    ]
    if fixture.websocket.sent_text != frame_texts:
        raise RuntimeError("lock contention changed downstream WebSocket frame order")
    if upstream.archived_request_ids != expected_archive_ids:
        raise RuntimeError("lock contention changed WebSocket archive attribution")
    if not pending_waiter.cancelled() or not send_waiter.cancelled():
        raise RuntimeError("cancelled lock waiter acquired the contended lock")
    return {
        "archive_request_ids": upstream.archived_request_ids,
        "event_count": summary.event_count,
        "pending_waiter_cancelled": pending_waiter.cancelled(),
        "send_waiter_cancelled": send_waiter.cancelled(),
    }


async def _verify_ready_enqueue_fairness() -> dict[str, int]:
    fixture = _make_fixture()
    upstream = _SignalingUpstream(_FRAME_MESSAGES)
    fixture.upstream = upstream
    marker_state = proxy_service._WebSocketRequestState(
        request_id="req-ws-ready-enqueue-marker",
        model="gpt-5.6-sol",
        service_tier=None,
        reasoning_effort=None,
        api_key_reservation=None,
        started_at=time.monotonic(),
        archive_request_id="archive-ws-ready-enqueue-marker",
    )
    event_count_when_enqueued: int | None = None

    async def enqueue_marker() -> None:
        nonlocal event_count_when_enqueued
        await upstream.first_receive_started.wait()
        async with fixture.pending_lock:
            event_count_when_enqueued = len(fixture.websocket.sent_text)
            fixture.pending_requests.append(marker_state)
            fixture.pending_requests.remove(marker_state)

    marker_task = asyncio.create_task(enqueue_marker(), name="benchmark-ready-enqueue-marker")
    relay_task = asyncio.create_task(_run_relay(fixture), name="benchmark-ready-enqueue-relay")
    try:
        async with asyncio.timeout(2.0):
            summary, _ = await asyncio.gather(relay_task, marker_task)
    finally:
        for task in (marker_task, relay_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(marker_task, relay_task, return_exceptions=True)

    if event_count_when_enqueued is None or event_count_when_enqueued >= _TOTAL_EVENT_COUNT:
        raise RuntimeError("fast WebSocket locks starved a ready request enqueue until the relay drained")
    return {
        "event_count_when_enqueued": event_count_when_enqueued,
        "relay_event_count": summary.event_count,
    }


async def _verify_correctness() -> str:
    fixture = _make_fixture()
    summary = await _run_relay(fixture)
    if summary.event_count != _TOTAL_EVENT_COUNT:
        raise RuntimeError("WebSocket relay benchmark lost downstream events")
    if summary.archive_count != _TOTAL_EVENT_COUNT + 1:
        raise RuntimeError("WebSocket relay benchmark lost archived upstream frames")
    if fixture.websocket.sent_text != list(_FRAME_TEXTS):
        raise RuntimeError("WebSocket relay changed downstream frame bytes or order")

    expected_archive_ids: list[str | None] = []
    expected_archive_ids.extend(
        f"archive_ws_relay_bench_{request_index:03d}" for request_index in range(_REQUEST_COUNT)
    )
    for _ in range(_DELTA_COUNT):
        expected_archive_ids.extend(
            f"archive_ws_relay_bench_{request_index:03d}" for request_index in range(_REQUEST_COUNT)
        )
    for request_index in range(_REQUEST_COUNT):
        expected_archive_ids.extend([f"archive_ws_relay_bench_{request_index:03d}"] * 2)
    expected_archive_ids.append(None)
    if fixture.upstream.archived_request_ids != expected_archive_ids:
        raise RuntimeError("WebSocket archive ownership changed or crossed requests")

    event_signature: list[list[object]] = []
    for text in fixture.websocket.sent_text:
        payload = json.loads(text)
        event_signature.append(
            [payload["type"], _response_id(payload), len(text), hashlib.sha256(text.encode()).hexdigest()]
        )
    correctness_payload = {
        "events": event_signature,
        "archive_request_ids": fixture.upstream.archived_request_ids,
        "malformed_created_unattributed": _verify_malformed_created_is_unattributed(),
        "contended_lock_contract": await _verify_contended_lock_contract(),
        "ready_enqueue_fairness": await _verify_ready_enqueue_fairness(),
    }
    digest = hashlib.sha256(json.dumps(correctness_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != _EXPECTED_CORRECTNESS_DIGEST:
        raise RuntimeError(
            "WebSocket relay benchmark correctness digest changed: "
            f"expected {_EXPECTED_CORRECTNESS_DIGEST}, got {digest}"
        )
    return digest


def _percentile_95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _consume_blackhole(summary: RelaySummary) -> None:
    global _BLACKHOLE
    _BLACKHOLE ^= summary.event_count ^ summary.total_bytes ^ summary.archive_count


async def _measure() -> Measurement:
    for _ in range(_WARMUP_COUNT):
        _consume_blackhole(await _run_relay(_make_fixture()))
    elapsed_samples: list[int] = []
    for _ in range(_SAMPLE_COUNT):
        fixture = _make_fixture()
        gc.collect()
        started = time.perf_counter_ns()
        summary = await _run_relay(fixture)
        elapsed_samples.append(time.perf_counter_ns() - started)
        _consume_blackhole(summary)
    return Measurement(
        median_ns_per_event=statistics.median(elapsed_samples) / _TOTAL_EVENT_COUNT,
        p95_ns_per_event=_percentile_95(elapsed_samples) / _TOTAL_EVENT_COUNT,
    )


async def main() -> None:
    correctness_digest = await _verify_correctness()
    measurement = await _measure()
    score = _REFERENCE_NS_PER_EVENT / measurement.median_ns_per_event * 1_000.0
    print(f"ASI correctness_digest={correctness_digest}")
    print(f"ASI blackhole={_BLACKHOLE}")
    print(f"ASI sample_count={_SAMPLE_COUNT}")
    print(f"ASI request_count={_REQUEST_COUNT}")
    print(f"ASI delta_count={_DELTA_COUNT}")
    print(f"ASI total_event_count={_TOTAL_EVENT_COUNT}")
    print(f"METRIC websocket_relay_score={score:.6f}")
    print(f"METRIC websocket_relay_ns_per_event={measurement.median_ns_per_event:.3f}")
    print(f"METRIC websocket_relay_p95_ns_per_event={measurement.p95_ns_per_event:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
