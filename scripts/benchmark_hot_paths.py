#!/usr/bin/env python3
"""Deterministic, offline performance workload for codex-lb hot paths."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import math
import sqlite3
import statistics
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.core.balancer.logic import (
    HEALTH_TIER_DRAINING,
    HEALTH_TIER_HEALTHY,
    HEALTH_TIER_PROBING,
    AccountState,
    RoutingCost,
    select_account,
)
from app.core.balancer.rendezvous_hash import select_node
from app.core.clients.proxy import SSEChunkIteratorProtocol, SSEContentProtocol, _iter_sse_events
from app.core.openai.chat_requests import ChatCompletionsRequest
from app.core.openai.parsing import parse_sse_event
from app.core.types import JsonValue
from app.core.utils.sse import format_sse_event
from app.db.models import AccountStatus
from app.modules.usage.repository import _latest_by_account_sqlite

_SAMPLE_COUNT = 21
_EXPECTED_CORRECTNESS_DIGEST = "5121fcaf328270ab68f8b936eeee5cf79a39bce7ca38e4e9ee65a5289134537c"
_REFERENCE_NS_PER_OPERATION: dict[str, float] = {
    "chat_mapping": 503_475.0,
    "account_selection": 48_262.0,
    "rendezvous_hash": 15_091.797,
    "sse_parse": 2_838.216,
    "usage_latest": 23_087.891,
    "sse_stream": 5_529.297,
}
_BLACKHOLE = 0

BenchmarkValue = int | str | tuple[int, int]
SyncWork = Callable[[], BenchmarkValue]
AsyncWork = Callable[[], Awaitable[BenchmarkValue]]


@dataclass(frozen=True, slots=True)
class SyncCase:
    name: str
    work: SyncWork
    iterations: int
    operations_per_iteration: int
    metric_suffix: str


@dataclass(frozen=True, slots=True)
class AsyncCase:
    name: str
    work: AsyncWork
    iterations: int
    operations_per_iteration: int
    metric_suffix: str


@dataclass(frozen=True, slots=True)
class Measurement:
    name: str
    median_batch_ns: float
    p95_batch_ns: float
    ns_per_operation: float
    p95_ns_per_operation: float
    metric_suffix: str


def _consume(value: BenchmarkValue) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return len(value)
    return value[0] ^ value[1]


def _percentile_95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    index = round(0.95 * (len(ordered) - 1))
    return ordered[index]


def _measure_sync(case: SyncCase) -> Measurement:
    global _BLACKHOLE

    warmup_guard = 0
    for _ in range(case.iterations):
        warmup_guard ^= _consume(case.work())
    _BLACKHOLE ^= warmup_guard

    samples: list[int] = []
    for _ in range(_SAMPLE_COUNT):
        gc.collect()
        guard = 0
        started = time.process_time_ns()
        for _ in range(case.iterations):
            guard ^= _consume(case.work())
        samples.append(time.process_time_ns() - started)
        _BLACKHOLE ^= guard

    median_batch_ns = float(statistics.median(samples))
    p95_batch_ns = float(_percentile_95(samples))
    operation_count = case.iterations * case.operations_per_iteration
    return Measurement(
        name=case.name,
        median_batch_ns=median_batch_ns,
        p95_batch_ns=p95_batch_ns,
        ns_per_operation=median_batch_ns / operation_count,
        p95_ns_per_operation=p95_batch_ns / operation_count,
        metric_suffix=case.metric_suffix,
    )


async def _measure_async(case: AsyncCase) -> Measurement:
    global _BLACKHOLE

    warmup_guard = 0
    for _ in range(case.iterations):
        warmup_guard ^= _consume(await case.work())
    _BLACKHOLE ^= warmup_guard

    samples: list[int] = []
    for _ in range(_SAMPLE_COUNT):
        gc.collect()
        guard = 0
        started = time.process_time_ns()
        for _ in range(case.iterations):
            guard ^= _consume(await case.work())
        samples.append(time.process_time_ns() - started)
        _BLACKHOLE ^= guard

    median_batch_ns = float(statistics.median(samples))
    p95_batch_ns = float(_percentile_95(samples))
    operation_count = case.iterations * case.operations_per_iteration
    return Measurement(
        name=case.name,
        median_batch_ns=median_batch_ns,
        p95_batch_ns=p95_batch_ns,
        ns_per_operation=median_batch_ns / operation_count,
        p95_ns_per_operation=p95_batch_ns / operation_count,
        metric_suffix=case.metric_suffix,
    )


def _build_chat_payload() -> dict[str, JsonValue]:
    messages: list[JsonValue] = [{"role": "system", "content": "Answer tersely and call tools when useful."}]
    for turn in range(12):
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Turn {turn}: inspect account routing state and summarize the deterministic result. "
                    + "x" * (96 + turn)
                ),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": f"Turn {turn} acknowledged; previous deterministic result was {turn * 17}.",
            }
        )

    tools: list[JsonValue] = []
    for tool_index in range(8):
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": f"lookup_metric_{tool_index}",
                    "description": "Look up a fixed benchmark metric.",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "account_id": {"type": "string"},
                            "window": {"type": "string", "enum": ["primary", "secondary"]},
                        },
                        "required": ["account_id", "window"],
                        "additionalProperties": False,
                    },
                },
            }
        )

    return {
        "model": "gpt-5.6-sol-extra-high-fast",
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "stream": True,
        "stream_options": {"include_usage": True, "include_obfuscation": False},
        "reasoning_effort": "high",
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "benchmark_result",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string"},
                        "score": {"type": "number"},
                    },
                    "required": ["account_id", "score"],
                    "additionalProperties": False,
                },
            },
        },
    }


_CHAT_PAYLOAD = _build_chat_payload()


def _chat_mapping_once() -> str:
    request = ChatCompletionsRequest.model_validate(_CHAT_PAYLOAD)
    responses = request.to_responses_request()
    return json.dumps(responses.to_payload(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


_FIXED_NOW = 1_700_000_000.0


def _build_account_states() -> tuple[list[AccountState], dict[str, RoutingCost]]:
    states: list[AccountState] = []
    costs: dict[str, RoutingCost] = {}
    health_tiers = (HEALTH_TIER_HEALTHY, HEALTH_TIER_DRAINING, HEALTH_TIER_PROBING)
    for index in range(128):
        status = AccountStatus.ACTIVE
        if index % 23 == 0:
            status = AccountStatus.PAUSED
        elif index % 19 == 0:
            status = AccountStatus.QUOTA_EXCEEDED
        elif index % 17 == 0:
            status = AccountStatus.RATE_LIMITED

        error_count = 3 if index % 29 == 0 and status == AccountStatus.ACTIVE else 0
        account_id = f"acc-{index:03d}"
        states.append(
            AccountState(
                account_id=account_id,
                status=status,
                used_percent=float((index * 17) % 97),
                reset_at=_FIXED_NOW + 7_200 + index,
                primary_reset_at=int(_FIXED_NOW + 3_600 + index * 11),
                cooldown_until=None,
                secondary_used_percent=float((index * 29) % 99),
                secondary_reset_at=int(_FIXED_NOW + 86_400 + index * 97),
                last_error_at=_FIXED_NOW - 5 if error_count else None,
                last_selected_at=_FIXED_NOW - float(index * 13),
                error_count=error_count,
                plan_type="pro" if index % 3 else "plus",
                capacity_credits=2_400.0 + index * 7.0,
                health_tier=health_tiers[index % len(health_tiers)],
                priority_used_percent=float((index * 11) % 93),
                priority_secondary_used_percent=float((index * 31) % 98),
                priority_reset_at=int(_FIXED_NOW + 172_800 + index * 53),
                priority_capacity_credits=3_000.0 + index * 5.0,
                routing_policy="preserve" if index % 31 == 0 else "normal",
            )
        )
        costs[account_id] = RoutingCost(total=float((index * 7) % 13), reason="fixed-benchmark")
    return states, costs


_ACCOUNT_STATES, _ROUTING_COSTS = _build_account_states()


def _account_selection_once() -> str:
    result = select_account(
        _ACCOUNT_STATES,
        now=_FIXED_NOW,
        prefer_earlier_reset=True,
        routing_strategy="relative_availability",
        allow_backoff_fallback=False,
        deterministic_probe=True,
        relative_availability_top_k=8,
        routing_costs=_ROUTING_COSTS,
    )
    if result.account is None:
        raise RuntimeError(result.error_message or "account selection failed")
    return result.account.account_id


_RENDEZVOUS_NODES = tuple(f"instance-{index:03d}.cluster.internal" for index in range(64))
_RENDEZVOUS_KEYS = tuple(f"codex-session-{index:05d}-{'x' * 48}" for index in range(256))


def _rendezvous_once() -> str:
    winners = [select_node(key, _RENDEZVOUS_NODES) or "" for key in _RENDEZVOUS_KEYS]
    return "\n".join(winners)


def _build_sse_blocks(count: int) -> tuple[str, ...]:
    blocks: list[str] = []
    for sequence in range(count):
        blocks.append(
            format_sse_event(
                {
                    "type": "response.output_text.delta",
                    "sequence_number": sequence,
                    "delta": f"token-{sequence:04d}-{'y' * (48 + sequence % 17)}",
                    "response_id": "resp_benchmark",
                }
            )
        )
    return tuple(blocks)


_SSE_PARSE_BLOCKS = _build_sse_blocks(256)
_STREAM_BLOCKS = _build_sse_blocks(512)
_STREAM_BYTES = "".join(_STREAM_BLOCKS).encode("utf-8")
_STREAM_CHUNKS = tuple(_STREAM_BYTES[offset : offset + 1024] for offset in range(0, len(_STREAM_BYTES), 1024))


def _sse_parse_once() -> int:
    signature = 0
    for block in _SSE_PARSE_BLOCKS:
        event = parse_sse_event(block)
        if event is None:
            raise RuntimeError("valid benchmark SSE event was rejected")
        signature = (signature * 1_000_003 + len(event.type)) & 0xFFFFFFFFFFFFFFFF
    return signature


class _FixedChunkIterator:
    def __init__(self, chunks: Sequence[bytes]) -> None:
        self._chunks = iter(chunks)

    def __aiter__(self) -> "_FixedChunkIterator":
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FixedContent:
    def __init__(self, chunks: Sequence[bytes]) -> None:
        self._chunks = chunks

    def iter_chunked(self, size: int) -> SSEChunkIteratorProtocol:
        del size
        return _FixedChunkIterator(self._chunks)


class _FixedResponse:
    def __init__(self, chunks: Sequence[bytes]) -> None:
        self.content: SSEContentProtocol = _FixedContent(chunks)


async def _sse_stream_once() -> str:
    response = _FixedResponse(_STREAM_CHUNKS)
    events = [
        event
        async for event in _iter_sse_events(
            response,
            idle_timeout_seconds=60.0,
            max_event_bytes=16 * 1024,
        )
    ]
    return "".join(events)


def _create_usage_database(root: Path) -> tuple[Path, tuple[str, ...]]:
    path = root / "usage-benchmark.sqlite3"
    account_ids = tuple(f"usage-acc-{index:03d}" for index in range(256))
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE accounts (id TEXT PRIMARY KEY);
            CREATE TABLE usage_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                recorded_at TIMESTAMP NOT NULL,
                window TEXT,
                used_percent REAL NOT NULL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                reset_at INTEGER,
                window_minutes INTEGER,
                credits_has INTEGER,
                credits_unlimited INTEGER,
                credits_balance REAL
            );
            CREATE INDEX idx_usage_window_account_latest
                ON usage_history (window, account_id, recorded_at DESC, id DESC);
            """
        )
        connection.executemany("INSERT INTO accounts (id) VALUES (?)", ((account_id,) for account_id in account_ids))
        rows: list[tuple[str, str, str, float, int, int, int, int, int, int, float]] = []
        for account_index, account_id in enumerate(account_ids):
            for history_index in range(24):
                rows.append(
                    (
                        account_id,
                        f"2026-01-01 00:{history_index:02d}:00",
                        "secondary",
                        float((account_index * 7 + history_index) % 101),
                        account_index * 10_000 + history_index * 13,
                        account_index * 1_000 + history_index * 5,
                        1_800_000_000 + history_index,
                        10_080,
                        1,
                        0,
                        5_000.0 - account_index - history_index / 10.0,
                    )
                )
        connection.executemany(
            """
            INSERT INTO usage_history (
                account_id, recorded_at, window, used_percent, input_tokens,
                output_tokens, reset_at, window_minutes, credits_has,
                credits_unlimited, credits_balance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    return path, account_ids


_USAGE_DB_PATH: Path
_USAGE_ACCOUNT_IDS: tuple[str, ...]


def _usage_latest_once() -> str:
    latest = _latest_by_account_sqlite(str(_USAGE_DB_PATH), "secondary", list(_USAGE_ACCOUNT_IDS))
    return ";".join(
        f"{account_id}:{latest[account_id].id}:{latest[account_id].used_percent:.1f}"
        for account_id in _USAGE_ACCOUNT_IDS
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _verify_correctness() -> str:
    chat_output = _chat_mapping_once()
    chat_payload = json.loads(chat_output)
    if chat_payload.get("model") != "gpt-5.6-sol-extra-high-fast":
        raise RuntimeError("chat mapping changed the benchmark model")
    if len(chat_payload.get("input", [])) != 24:
        raise RuntimeError("chat mapping changed the benchmark message count")
    if len(chat_payload.get("tools", [])) != 8:
        raise RuntimeError("chat mapping changed the benchmark tool count")

    selected_account = _account_selection_once()
    rendezvous_output = _rendezvous_once()
    parsed_signature = _sse_parse_once()
    streamed_output = await _sse_stream_once()
    if streamed_output.encode("utf-8") != _STREAM_BYTES:
        raise RuntimeError("SSE stream parser changed bytes or event ordering")

    usage_output = _usage_latest_once()
    latest = _latest_by_account_sqlite(str(_USAGE_DB_PATH), "secondary", list(_USAGE_ACCOUNT_IDS))
    if len(latest) != len(_USAGE_ACCOUNT_IDS):
        raise RuntimeError("usage latest query dropped accounts")
    for account_index in (0, 127, 255):
        account_id = _USAGE_ACCOUNT_IDS[account_index]
        expected_used = float((account_index * 7 + 23) % 101)
        if latest[account_id].used_percent != expected_used:
            raise RuntimeError(f"usage latest query returned the wrong row for {account_id}")

    components = (
        _sha256_text(chat_output),
        selected_account,
        _sha256_text(rendezvous_output),
        str(parsed_signature),
        hashlib.sha256(streamed_output.encode("utf-8")).hexdigest(),
        _sha256_text(usage_output),
    )
    digest = hashlib.sha256("\n".join(components).encode("utf-8")).hexdigest()
    if digest != _EXPECTED_CORRECTNESS_DIGEST:
        raise RuntimeError(
            "benchmark correctness digest changed: "
            f"expected {_EXPECTED_CORRECTNESS_DIGEST}, got {digest}; components={components}"
        )
    return digest


async def _run_benchmarks() -> list[Measurement]:
    sync_cases = (
        SyncCase("chat_mapping", _chat_mapping_once, 120, 1, "request"),
        SyncCase("account_selection", _account_selection_once, 500, 1, "request"),
        SyncCase("rendezvous_hash", _rendezvous_once, 2, len(_RENDEZVOUS_KEYS), "key"),
        SyncCase("sse_parse", _sse_parse_once, 12, len(_SSE_PARSE_BLOCKS), "event"),
        SyncCase("usage_latest", _usage_latest_once, 2, len(_USAGE_ACCOUNT_IDS), "account"),
    )
    async_cases = (AsyncCase("sse_stream", _sse_stream_once, 6, len(_STREAM_BLOCKS), "event"),)

    measurements = [_measure_sync(case) for case in sync_cases]
    measurements.extend([await _measure_async(case) for case in async_cases])
    return measurements


def _hot_path_score(measurements: Sequence[Measurement]) -> float:
    ratios = [
        measurement.ns_per_operation / _REFERENCE_NS_PER_OPERATION[measurement.name] for measurement in measurements
    ]
    return math.exp(sum(math.log(ratio) for ratio in ratios) / len(ratios)) * 1_000.0


async def main() -> None:
    global _USAGE_DB_PATH, _USAGE_ACCOUNT_IDS

    with tempfile.TemporaryDirectory(prefix="codex-lb-autoresearch-") as temporary_directory:
        _USAGE_DB_PATH, _USAGE_ACCOUNT_IDS = _create_usage_database(Path(temporary_directory))
        correctness_digest = await _verify_correctness()
        measurements = await _run_benchmarks()

    hot_path_score = _hot_path_score(measurements)
    print(f"ASI correctness_digest={correctness_digest}")
    print(f"ASI blackhole={_BLACKHOLE}")
    print(f"ASI sample_count={_SAMPLE_COUNT}")
    print(f"METRIC hot_path_score={hot_path_score:.6f}")
    for measurement in measurements:
        print(f"METRIC {measurement.name}_ns_per_{measurement.metric_suffix}={measurement.ns_per_operation:.3f}")
        print(
            f"METRIC {measurement.name}_p95_ns_per_{measurement.metric_suffix}={measurement.p95_ns_per_operation:.3f}"
        )


if __name__ == "__main__":
    asyncio.run(main())
