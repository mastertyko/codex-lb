#!/usr/bin/env python3
"""Deterministic SQLite workload for codex-lb dashboard query hot paths."""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import math
import statistics
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import AccountStatus, Base, RequestKind
from app.modules.request_logs.repository import RequestLogsRepository
from app.modules.usage.repository import AdditionalUsageRepository

_ACCOUNT_TABLE = Base.metadata.tables["accounts"]
_ADDITIONAL_USAGE_TABLE = Base.metadata.tables["additional_usage_history"]
_REQUEST_LOG_TABLE = Base.metadata.tables["request_logs"]


_SAMPLE_COUNT = 21
_ACCOUNT_COUNT = 64
_ADDITIONAL_ROWS_PER_WINDOW = 8
_REQUEST_LOG_COUNT = 40_000
_FIXED_NOW = datetime(2026, 6, 1, 12, 0, 0)
_ADDITIONAL_SINCE = datetime(2026, 1, 1, 0, 1, 0)
_EXPECTED_CORRECTNESS_DIGEST = "8bf2c49c95401c459c3c47d174de152dd89a82243419a90001f8365524f8ae39"
_REFERENCE_NS_PER_OPERATION: dict[str, float] = {
    "additional_latest": 446_057.289,
    "dashboard_aggregate": 99_574_208.0,
    "request_page": 25_737_729.5,
}
_BLACKHOLE = 0

AsyncWork = Callable[[], Awaitable[str]]


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


@dataclass(frozen=True, slots=True)
class StatementCounts:
    additional_latest: int
    dashboard_aggregate: int
    request_page: int


def _percentile_95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


async def _measure_async(case: AsyncCase) -> Measurement:
    global _BLACKHOLE

    warmup_guard = 0
    for _ in range(case.iterations):
        warmup_guard ^= len(await case.work())
    _BLACKHOLE ^= warmup_guard

    samples: list[int] = []
    for _ in range(_SAMPLE_COUNT):
        gc.collect()
        guard = 0
        started = time.perf_counter_ns()
        for _ in range(case.iterations):
            guard ^= len(await case.work())
        samples.append(time.perf_counter_ns() - started)
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


def _dashboard_db_score(measurements: Sequence[Measurement]) -> float:
    ratios = [
        _REFERENCE_NS_PER_OPERATION[measurement.name] / measurement.ns_per_operation for measurement in measurements
    ]
    return math.exp(sum(math.log(ratio) for ratio in ratios) / len(ratios)) * 1_000.0


def _configure_sync_database(database_path: Path) -> None:
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA synchronous=NORMAL")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("PRAGMA temp_store=MEMORY")
            connection.exec_driver_sql("PRAGMA cache_size=-65536")
            Base.metadata.create_all(
                connection,
                tables=[
                    _ACCOUNT_TABLE,
                    _ADDITIONAL_USAGE_TABLE,
                    _REQUEST_LOG_TABLE,
                ],
            )
            _insert_accounts(connection)
            _insert_additional_usage(connection)
            _insert_request_logs(connection)
    finally:
        engine.dispose()


def _insert_accounts(connection) -> None:
    rows = []
    for index in range(_ACCOUNT_COUNT):
        account_id = f"db-acc-{index:03d}"
        rows.append(
            {
                "id": account_id,
                "codex_installation_id": f"00000000-0000-0000-0000-{index:012d}",
                "email": f"{account_id}@example.com",
                "plan_type": "pro" if index % 3 else "plus",
                "routing_policy": "normal",
                "access_token_encrypted": b"benchmark-access",
                "refresh_token_encrypted": b"benchmark-refresh",
                "id_token_encrypted": b"benchmark-id",
                "last_refresh": _FIXED_NOW,
                "status": AccountStatus.ACTIVE,
                "deactivation_reason": None,
                "limit_warmup_enabled": False,
                "security_work_authorized": False,
            }
        )
    connection.execute(_ACCOUNT_TABLE.insert(), rows)


def _insert_additional_usage(connection) -> None:
    rows = []
    row_id = 1
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    for account_index in range(_ACCOUNT_COUNT):
        account_id = f"db-acc-{account_index:03d}"
        for window_index, window in enumerate(("primary", "secondary")):
            for history_index in range(_ADDITIONAL_ROWS_PER_WINDOW):
                recorded_minute = min(history_index, _ADDITIONAL_ROWS_PER_WINDOW - 2)
                alias_winner_candidate = history_index == _ADDITIONAL_ROWS_PER_WINDOW - 1 and account_index % 4 == 0
                rows.append(
                    {
                        "id": row_id,
                        "account_id": account_id,
                        "quota_key": "legacy_unknown" if alias_winner_candidate else "codex_spark",
                        "limit_name": "GPT-5.3-Codex-Spark",
                        "metered_feature": "codex_bengalfox",
                        "window": window,
                        "used_percent": float((account_index * 11 + window_index * 17 + history_index * 13) % 100),
                        "reset_at": 1_800_000_000 + history_index,
                        "window_minutes": 300 if window == "primary" else 10_080,
                        "recorded_at": base_time + timedelta(minutes=recorded_minute),
                    }
                )
                row_id += 1
    connection.execute(_ADDITIONAL_USAGE_TABLE.insert(), rows)


def _insert_request_logs(connection) -> None:
    rows = []
    span_seconds = 15 * 24 * 60 * 60
    efforts = (None, "low", "medium", "high")
    service_tiers = (None, "default", "priority")
    for index in range(_REQUEST_LOG_COUNT):
        requested_at = _FIXED_NOW - timedelta(seconds=(index * 37) % span_seconds)
        if index % 31 == 0:
            status = "other"
            error_code = None
        elif index % 7 == 0:
            status = "error"
            error_code = "server_error" if index % 21 == 0 else "rate_limit_exceeded"
        else:
            status = "success"
            error_code = None
        rows.append(
            {
                "id": index + 1,
                "account_id": f"db-acc-{index % _ACCOUNT_COUNT:03d}",
                "request_id": f"db-request-{index:06d}",
                "request_kind": RequestKind.WARMUP.value if index % 20 == 0 else RequestKind.NORMAL.value,
                "requested_at": requested_at,
                "deleted_at": requested_at if index % 101 == 0 else None,
                "model": f"gpt-5.{index % 8}",
                "plan_type": "pro" if index % 3 else "plus",
                "source": "account",
                "service_tier": service_tiers[index % len(service_tiers)],
                "input_tokens": 100 + index % 300,
                "output_tokens": 20 + index % 80,
                "cached_input_tokens": index % 50,
                "reasoning_tokens": index % 30,
                "cost_usd": float(index % 100) / 1_000_000.0,
                "reasoning_effort": efforts[index % len(efforts)],
                "latency_ms": 50 + index % 500,
                "status": status,
                "error_code": error_code,
                "error_message": "fixed benchmark error" if status == "error" else None,
            }
        )
        if len(rows) == 5_000:
            connection.execute(_REQUEST_LOG_TABLE.insert(), rows)
            rows.clear()
    if rows:
        connection.execute(_REQUEST_LOG_TABLE.insert(), rows)


class DatabaseWorkloads:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._additional = AdditionalUsageRepository(session)
        self._logs = RequestLogsRepository(session)
        self._account_ids = [f"db-acc-{index:03d}" for index in range(_ACCOUNT_COUNT)]

    async def additional_latest(self) -> str:
        primary = await self._additional.latest_by_quota_key(
            "codex_spark",
            "primary",
            account_ids=self._account_ids,
            since=_ADDITIONAL_SINCE,
        )
        secondary = await self._additional.latest_by_quota_key(
            "codex_spark",
            "secondary",
            account_ids=self._account_ids,
            since=_ADDITIONAL_SINCE,
        )
        payload = {
            "primary": [
                [
                    account_id,
                    primary[account_id].id,
                    primary[account_id].quota_key,
                    primary[account_id].used_percent,
                    primary[account_id].recorded_at.isoformat(),
                ]
                for account_id in self._account_ids
            ],
            "secondary": [
                [
                    account_id,
                    secondary[account_id].id,
                    secondary[account_id].quota_key,
                    secondary[account_id].used_percent,
                    secondary[account_id].recorded_at.isoformat(),
                ]
                for account_id in self._account_ids
            ],
        }
        self._session.expunge_all()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    async def dashboard_aggregate(self) -> str:
        current_start = _FIXED_NOW - timedelta(days=7)
        previous_start = current_start - timedelta(days=7)
        buckets = await self._logs.aggregate_by_bucket(current_start, 6 * 60 * 60)
        current = await self._logs.aggregate_activity_between(current_start, _FIXED_NOW)
        previous = await self._logs.aggregate_activity_between(previous_start, current_start)
        top_error = await self._logs.top_error_between(current_start, _FIXED_NOW)
        earliest = await self._logs.earliest_activity_at()
        payload = {
            "buckets": [
                [
                    row.bucket_epoch,
                    row.model,
                    row.service_tier,
                    row.request_count,
                    row.error_count,
                    row.input_tokens,
                    row.output_tokens,
                    row.cached_input_tokens,
                    row.reasoning_tokens,
                    round(row.cost_usd, 12),
                ]
                for row in buckets
            ],
            "current": [
                current.request_count,
                current.error_count,
                current.input_tokens,
                current.output_tokens,
                current.cached_input_tokens,
                round(current.cost_usd, 12),
            ],
            "previous": [
                previous.request_count,
                previous.error_count,
                previous.input_tokens,
                previous.output_tokens,
                previous.cached_input_tokens,
                round(previous.cost_usd, 12),
            ],
            "top_error": top_error,
            "earliest": earliest.isoformat() if earliest is not None else None,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    async def request_page(self) -> str:
        logs, total = await self._logs.list_recent(limit=50, offset=20_000)
        payload = {
            "total": total,
            "rows": [[log.id, log.request_id, log.requested_at.isoformat(), log.status] for log in logs],
        }
        self._session.expunge_all()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


async def _count_statements(engine: AsyncEngine, work: AsyncWork) -> tuple[int, str]:
    statement_count = 0

    def _capture(_conn, _cursor, _statement, _parameters, _context, _executemany) -> None:
        nonlocal statement_count
        statement_count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _capture)
    try:
        output = await work()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)
    return statement_count, output


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _verify_correctness(
    engine: AsyncEngine,
    workloads: DatabaseWorkloads,
) -> tuple[str, StatementCounts]:
    additional_statements, additional_output = await _count_statements(engine, workloads.additional_latest)
    dashboard_statements, dashboard_output = await _count_statements(engine, workloads.dashboard_aggregate)
    page_statements, page_output = await _count_statements(engine, workloads.request_page)

    additional_payload = json.loads(additional_output)
    if len(additional_payload["primary"]) != _ACCOUNT_COUNT:
        raise RuntimeError("additional latest primary result dropped accounts")
    if len(additional_payload["secondary"]) != _ACCOUNT_COUNT:
        raise RuntimeError("additional latest secondary result dropped accounts")
    if additional_payload["primary"][0][3] != 91.0:
        raise RuntimeError("additional latest tie-break changed for primary db-acc-000")
    if additional_payload["secondary"][0][3] != 95.0:
        raise RuntimeError("additional latest tie-break changed for secondary db-acc-000")

    dashboard_payload = json.loads(dashboard_output)
    if dashboard_payload["current"][0] <= 0 or dashboard_payload["previous"][0] <= 0:
        raise RuntimeError("dashboard activity windows unexpectedly empty")
    if not dashboard_payload["buckets"]:
        raise RuntimeError("dashboard buckets unexpectedly empty")
    if dashboard_payload["top_error"] != "rate_limit_exceeded":
        raise RuntimeError("dashboard top-error contract changed")

    page_payload = json.loads(page_output)
    if page_payload["total"] <= 20_050 or len(page_payload["rows"]) != 50:
        raise RuntimeError("request-log deep page contract changed")

    counts = StatementCounts(
        additional_latest=additional_statements,
        dashboard_aggregate=dashboard_statements,
        request_page=page_statements,
    )
    if not 1 <= counts.additional_latest <= 2 * (_ACCOUNT_COUNT + 1):
        raise RuntimeError(f"unexpected additional latest statement count: {counts.additional_latest}")
    if not 1 <= counts.dashboard_aggregate <= 5:
        raise RuntimeError(f"unexpected dashboard aggregate statement count: {counts.dashboard_aggregate}")
    if not 1 <= counts.request_page <= 2:
        raise RuntimeError(f"unexpected request page statement count: {counts.request_page}")

    components = (
        _sha256_text(additional_output),
        _sha256_text(dashboard_output),
        _sha256_text(page_output),
    )
    digest = hashlib.sha256("\n".join(components).encode("utf-8")).hexdigest()
    if digest != _EXPECTED_CORRECTNESS_DIGEST:
        raise RuntimeError(
            "benchmark correctness digest changed: "
            f"expected {_EXPECTED_CORRECTNESS_DIGEST}, got {digest}; components={components}"
        )
    return digest, counts


async def _run_benchmarks(workloads: DatabaseWorkloads) -> list[Measurement]:
    cases = (
        AsyncCase(
            "additional_latest",
            workloads.additional_latest,
            1,
            _ACCOUNT_COUNT * 2,
            "account_window",
        ),
        AsyncCase(
            "dashboard_aggregate",
            workloads.dashboard_aggregate,
            1,
            1,
            "bundle",
        ),
        AsyncCase(
            "request_page",
            workloads.request_page,
            2,
            1,
            "request",
        ),
    )
    return [await _measure_async(case) for case in cases]


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="codex-lb-dashboard-autoresearch-") as temporary_directory:
        database_path = Path(temporary_directory) / "dashboard-benchmark.sqlite3"
        _configure_sync_database(database_path)
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path}",
            pool_size=1,
            max_overflow=0,
        )
        try:
            async with engine.begin() as connection:
                await connection.execute(text("PRAGMA query_only=ON"))
                await connection.execute(text("PRAGMA foreign_keys=ON"))
                await connection.execute(text("PRAGMA temp_store=MEMORY"))
                await connection.execute(text("PRAGMA cache_size=-65536"))
                await connection.execute(text("PRAGMA busy_timeout=0"))
            session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with session_factory() as session:
                workloads = DatabaseWorkloads(session)
                correctness_digest, counts = await _verify_correctness(engine, workloads)
                measurements = await _run_benchmarks(workloads)
        finally:
            await engine.dispose()

    score = _dashboard_db_score(measurements)
    print(f"ASI correctness_digest={correctness_digest}")
    print(f"ASI blackhole={_BLACKHOLE}")
    print(f"ASI sample_count={_SAMPLE_COUNT}")
    print(f"ASI account_count={_ACCOUNT_COUNT}")
    print(f"ASI request_log_count={_REQUEST_LOG_COUNT}")
    print(f"METRIC dashboard_db_score={score:.6f}")
    print(f"METRIC additional_latest_statements={counts.additional_latest}")
    print(f"METRIC dashboard_aggregate_statements={counts.dashboard_aggregate}")
    print(f"METRIC request_page_statements={counts.request_page}")
    for measurement in measurements:
        print(f"METRIC {measurement.name}_ns_per_{measurement.metric_suffix}={measurement.ns_per_operation:.3f}")
        print(
            f"METRIC {measurement.name}_p95_ns_per_{measurement.metric_suffix}={measurement.p95_ns_per_operation:.3f}"
        )


if __name__ == "__main__":
    asyncio.run(main())
