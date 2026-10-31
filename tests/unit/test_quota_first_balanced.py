from __future__ import annotations

import asyncio
import time
from collections import Counter

import pytest

from app.db.models import AccountStatus, StickySessionKind
from app.modules.proxy._load_balancer.quota_first import account_allowed
from app.modules.proxy._load_balancer.types import RuntimeState
from app.modules.proxy.affinity import _codex_backend_identity, _codex_session_selection_key
from app.modules.proxy.load_balancer import LoadBalancer
from tests.unit.test_load_balancer_concurrency import (
    _make_account,
    _make_cap_spillover_balancer,
    _repo_factory,
    _StubAccountsRepository,
    _StubUsageRepository,
    _usage_row,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent", [False, True])
async def test_fresh_sibling_threads_balance_without_inheriting_process_and_keep_owners(concurrent):
    balancer, owner, alternate, sticky = _make_cap_spillover_balancer("quota-first")
    assert alternate is not None
    process = "one-process"
    seed = _codex_session_selection_key(process)
    sticky.account_ids_by_key = {seed: owner.id}

    async def select(index):
        key = _codex_backend_identity({"session-id": process, "thread-id": f"thread-{index}"}).thread_selection_key
        result = await balancer.select_account(
            routing_strategy="quota_first_balanced",
            sticky_key=key,
            sticky_kind=StickySessionKind.PROMPT_CACHE,
            sticky_source="thread_header",
            legacy_sticky_key=process,
            sticky_seed_key=seed,
            sticky_seed_kind=StickySessionKind.CODEX_SESSION,
        )
        assert result.account is not None
        return result.account.id

    if concurrent:
        accounts = await asyncio.gather(*(select(index) for index in range(20)))
    else:
        accounts = []
        for index in range(20):
            accounts.append(await select(index))
            # A busy established chat must not bias the next fresh allocation.
            for _ in range(3):
                assert await select(0) == accounts[0]
    assert Counter(accounts) == {owner.id: 10, alternate.id: 10}
    assert sticky.account_ids_by_key[seed] == owner.id
    assert balancer._fresh_thread_allocations == {owner.id: 10, alternate.id: 10}


def funding_pool(*, other_usage=30.0, other_status=AccountStatus.ACTIVE, credits=True):
    credit = _make_account("credit")
    other = _make_account("subscription")
    other.status = other_status
    deadline = int(time.time()) + 3600
    primary = {a.id: _usage_row(i, a.id, window="primary", reset_at=deadline) for i, a in enumerate([credit, other])}
    secondary = {
        a.id: _usage_row(i + 10, a.id, window="secondary", reset_at=deadline) for i, a in enumerate([credit, other])
    }
    secondary[credit.id].used_percent = 100.0
    secondary[credit.id].credits_has = credits
    secondary[credit.id].credits_balance = 5.0 if credits else 0.0
    if other_usage is None:
        del primary[other.id]
        del secondary[other.id]
    else:
        secondary[other.id].used_percent = other_usage
    repository = _StubUsageRepository(primary, secondary)
    balancer = LoadBalancer(lambda: _repo_factory(_StubAccountsRepository([credit, other]), repository))
    return balancer, credit, other, repository


@pytest.mark.asyncio
@pytest.mark.parametrize("pressure", ["none", "excluded", "cooldown", "overload", "quota-status-without-evidence"])
async def test_remaining_subscription_blocks_credit_despite_transient_pressure(pressure):
    balancer, credit, other, _ = funding_pool()
    kwargs = {}
    if pressure == "excluded":
        kwargs["exclude_account_ids"] = [other.id]
    if pressure == "cooldown":
        balancer._runtime[other.id] = RuntimeState(cooldown_until=time.time() + 300)
    if pressure == "overload":
        balancer._runtime[other.id] = RuntimeState(overload_backoff_until=time.time() + 300)
    if pressure == "quota-status-without-evidence":
        other.status = AccountStatus.RATE_LIMITED
        other.reset_at = int(time.time() + 300)
    result = await balancer.select_account(routing_strategy="quota_first_balanced", **kwargs)
    assert result.account is None or result.account.id == other.id
    assert not await account_allowed(balancer, credit.id, model=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("other_usage", [None, 99.9])
async def test_unknown_and_last_fraction_of_subscription_block_credits(other_usage):
    balancer, credit, _, _ = funding_pool(other_usage=other_usage)
    result = await balancer.select_account(routing_strategy="quota_first_balanced")
    assert result.account is not None
    assert result.account.id != credit.id


@pytest.mark.asyncio
@pytest.mark.parametrize("other_status", [AccountStatus.ACTIVE, AccountStatus.PAUSED, AccountStatus.DEACTIVATED])
async def test_credits_admitted_only_when_eligible_subscriptions_are_exhausted(other_status):
    balancer, credit, _, _ = funding_pool(other_usage=100.0, other_status=other_status)
    result = await balancer.select_account(routing_strategy="quota_first_balanced")
    assert result.account is not None
    assert result.account.id == credit.id
    assert await account_allowed(balancer, credit.id, model=None)


@pytest.mark.asyncio
async def test_creditless_exhaustion_does_not_admit_an_account():
    balancer, _, _, _ = funding_pool(other_usage=100.0, credits=False)
    result = await balancer.select_account(routing_strategy="quota_first_balanced")
    assert result.account is None


@pytest.mark.asyncio
async def test_key_scope_can_exhaust_independently_and_hard_owner_cannot_cross_account():
    balancer, credit, other, _ = funding_pool()
    scoped = await balancer.select_account(routing_strategy="quota_first_balanced", account_ids=[credit.id])
    assert scoped.account is not None and scoped.account.id == credit.id
    pinned = await balancer.select_account(
        routing_strategy="quota_first_balanced", required_account_id=credit.id, required_continuity_owner=True
    )
    assert pinned.account is None
    assert other.id != credit.id


@pytest.mark.asyncio
async def test_existing_strategy_can_still_select_credit_owner():
    balancer, credit, other, _ = funding_pool()
    result = await balancer.select_account(
        routing_strategy="round_robin", required_account_id=credit.id, required_continuity_owner=True
    )
    assert result.account is not None and result.account.id == credit.id


@pytest.mark.asyncio
async def test_http_bridge_submit_rejects_credit_without_retiring_context(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.core.clients.proxy import ProxyResponseError
    from app.modules.proxy import service as proxy_service
    from app.modules.proxy._service.http_bridge import request_submit
    from tests.unit.test_http_bridge_idle_leases import _make_bridge_session, _make_lease

    balancer, credit, _, _ = funding_pool()
    service = proxy_service.ProxyService(nullcontext())
    service._load_balancer = balancer
    session = _make_bridge_session()
    session.account = credit
    session.account_lease = _make_lease("held")
    service._maybe_prewarm_http_bridge_session = AsyncMock()
    service._acquire_request_state_response_create_admission = AsyncMock()
    service._http_bridge_text_with_account_installation_id = lambda s, r, t: t
    settings = SimpleNamespace(routing_strategy="quota_first_balanced")
    monkeypatch.setattr(
        request_submit, "_service_get_settings_cache", lambda: SimpleNamespace(cached_row=lambda: settings)
    )
    request = proxy_service._WebSocketRequestState(
        request_id="quota-bridge",
        model=None,
        service_tier=None,
        reasoning_effort=None,
        api_key_reservation=None,
        started_at=time.monotonic(),
        transport="http",
        skip_request_log=True,
    )
    with pytest.raises(ProxyResponseError) as error:
        await service._submit_http_bridge_request(session, request_state=request, text_data="{}", queue_limit=8)
    assert error.value.payload["error"]["code"] == "quota_first_owner_unavailable"
    assert not session.closed
    assert not session.upstream_control.retire_after_drain
    assert session.pending_requests == [] or len(session.pending_requests) == 0
    assert session.queued_request_count == 0
    assert session.admission_waiter_count == 0
    session.upstream.close.assert_not_awaited()
