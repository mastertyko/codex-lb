from __future__ import annotations

import asyncio
import time
from collections import Counter

import pytest

from app.core.balancer.logic import AccountState, select_account
from app.db.models import AccountStatus, StickySessionKind
from app.modules.proxy.load_balancer import LoadBalancer
from tests.unit.test_load_balancer_concurrency import (
    _make_account,
    _repo_factory,
    _StubAccountsRepository,
    _StubStickySessionsRepository,
    _StubUsageRepository,
    _usage_row,
)

pytestmark = pytest.mark.unit


def test_quota_catchup_overrides_old_counts_then_equal_band_balances():
    states = [
        AccountState(account_id=name, status=AccountStatus.ACTIVE, used_percent=used, fresh_thread_allocations=count)
        for name, used, count in [("unused", 0.0, 100), ("middle", 37.0, 1), ("busy", 46.0, 0)]
    ]
    assert select_account(states, routing_strategy="quota_first_balanced").account is states[0]
    states[0].used_percent = 38.0
    # The unused account has caught up with middle; stop preferring it.
    assert select_account(states, routing_strategy="quota_first_balanced").account is states[1]
    for state in states:
        state.used_percent = 46.0
        state.fresh_thread_allocations = 0
    selected = Counter()
    for _ in range(12):
        winner = select_account(states, routing_strategy="quota_first_balanced").account
        assert winner is not None
        selected[winner.account_id] += 1
        winner.fresh_thread_allocations += 1
    assert selected == {"unused": 4, "middle": 4, "busy": 4}


@pytest.mark.parametrize("unknown", [None, float("nan"), float("inf")])
def test_unknown_usage_is_not_free_capacity(unknown):
    states = [
        AccountState(account_id="unknown", status=AccountStatus.ACTIVE, used_percent=unknown),
        AccountState(account_id="measured", status=AccountStatus.ACTIVE, used_percent=46),
    ]
    assert select_account(states, routing_strategy="quota_first_balanced").account is states[1]


def test_most_constrained_window_and_scoped_priority_are_used():
    short = AccountState(account_id="short", status=AccountStatus.ACTIVE, used_percent=70, secondary_used_percent=0)
    long = AccountState(account_id="long", status=AccountStatus.ACTIVE, used_percent=10, secondary_used_percent=37)
    assert select_account([short, long], routing_strategy="quota_first_balanced").account is long
    short.priority_used_percent = 5
    short.priority_secondary_used_percent = 6
    short.limit_scoped_usage = True
    assert select_account([short, long], routing_strategy="quota_first_balanced").account is short
    short.priority_secondary_used_percent = None
    short.secondary_used_percent = 90  # unrelated standard quota must stay ignored
    assert select_account([short, long], routing_strategy="quota_first_balanced").account is short


def test_reset_breaks_equal_band_count_tie_but_not_catchup():
    now = time.time()
    a = AccountState(
        account_id="early",
        status=AccountStatus.ACTIVE,
        used_percent=37,
        secondary_reset_at=int(now + 3600),
        last_selected_at=now,
    )
    b = AccountState(
        account_id="late", status=AccountStatus.ACTIVE, used_percent=38, secondary_reset_at=int(now + 86400 * 2)
    )
    assert select_account([a, b], now=now, routing_strategy="quota_first_balanced").account is a
    b.used_percent = 0
    assert select_account([a, b], now=now, routing_strategy="quota_first_balanced").account is b


def make_pool():
    accounts = [_make_account(name) for name in ["unused", "middle", "busy"]]
    deadline = int(time.time()) + 3600
    rows = {a.id: _usage_row(i, a.id, window="primary", reset_at=deadline) for i, a in enumerate(accounts)}
    for row, used in zip(rows.values(), [0.0, 37.0, 46.0], strict=True):
        row.used_percent = used
        row.window_minutes = 10080  # weekly reported as primary by Pro 500
    usage = _StubUsageRepository(rows, {})
    sticky = _StubStickySessionsRepository()
    sticky.account_ids_by_key = {}
    balancer = LoadBalancer(lambda: _repo_factory(_StubAccountsRepository(accounts), usage, sticky))
    return balancer, usage, sticky


@pytest.mark.asyncio
async def test_real_selector_keeps_busy_owner_and_catches_up_concurrent_new_threads():
    balancer, usage, sticky = make_pool()
    sticky.account_ids_by_key["old"] = "busy"
    balancer._fresh_thread_allocations["unused"] = 100

    async def pick(key):
        result = await balancer.select_account(
            routing_strategy="quota_first_balanced",
            sticky_key=key,
            sticky_kind=StickySessionKind.PROMPT_CACHE,
            sticky_source="thread_header",
        )
        assert result.account is not None
        return result.account.id

    assert await pick("old") == "busy"
    assert await asyncio.gather(*(pick(f"new-{i}") for i in range(6))) == ["unused"] * 6
    usage._primary["unused"].used_percent = 39
    balancer._selection_inputs_cache.invalidate()
    assert await pick("caught-up") == "middle"
    assert await pick("old") == "busy"
    assert await pick("new-0") == "unused"


@pytest.mark.asyncio
async def test_live_leases_spread_a_burst_and_release_cleanly():
    balancer, usage, _ = make_pool()
    usage._primary["middle"].used_percent = 0
    usage._primary["busy"].used_percent = 0

    async def pick():
        return await balancer.select_account(routing_strategy="quota_first_balanced", lease_kind="response_create")

    results = await asyncio.gather(*(pick() for _ in range(6)))
    assert all(r.account is not None and r.lease is not None for r in results)
    assert Counter(r.account.id for r in results if r.account) == {"unused": 2, "middle": 2, "busy": 2}
    for result in results:
        await balancer.release_account_lease(result.lease)
    assert all(state.inflight_response_creates == 0 for state in balancer._runtime.values())


@pytest.mark.asyncio
async def test_reset_normalization_allows_new_quota_to_catch_up():
    balancer, usage, _ = make_pool()
    usage._primary["unused"].used_percent = 80
    usage._primary["unused"].reset_at = int(time.time()) - 60
    result = await balancer.select_account(routing_strategy="quota_first_balanced")
    assert result.account is not None and result.account.id == "unused"


@pytest.mark.asyncio
async def test_reserved_work_can_outweigh_a_small_quota_advantage():
    balancer, usage, _ = make_pool()
    usage._primary["middle"].used_percent = 6
    leases = [await balancer.acquire_account_lease("unused", kind="response_create") for _ in range(4)]
    assert all(leases)
    try:
        result = await balancer.select_account(routing_strategy="quota_first_balanced")
        assert result.account is not None and result.account.id == "middle"
    finally:
        for lease in leases:
            await balancer.release_account_lease(lease)
    result = await balancer.select_account(routing_strategy="quota_first_balanced")
    assert result.account is not None and result.account.id == "unused"
