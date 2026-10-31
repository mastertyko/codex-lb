from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Iterable
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

from app.core.balancer import (
    TRAFFIC_CLASS_FOREGROUND,
    AccountState,
    ResetPreferenceWindow,
    RoutingCostsByAccount,
    RoutingStrategy,
    TrafficClass,
)
from app.core.clock import Clock
from app.db.models import Account, StickySessionKind
from app.modules.proxy._load_balancer.sticky_selection import _STICKY_EXISTING_UNSET, _StickySelectionOutcome
from app.modules.proxy._load_balancer.sticky_selection import _select_with_stickiness as _run_select_with_stickiness
from app.modules.proxy._load_balancer.types import RuntimeState
from app.modules.proxy.sticky_repository import StickySessionsRepository

if TYPE_CHECKING:
    from app.modules.proxy.load_balancer import LoadBalancer, SelectionInputs


def filter_funding_inputs(
    inputs: SelectionInputs,
    *,
    now: float,
    build_states: Callable[..., tuple[list[AccountState], dict[str, Account]]],
) -> SelectionInputs:
    # Detached states prevent funding checks from changing health, clocks or leases.
    states, _ = build_states(
        accounts=inputs.accounts,
        latest_primary=inputs.latest_primary,
        latest_secondary=inputs.latest_secondary,
        latest_monthly=inputs.latest_monthly,
        runtime={},
        now=now,
        ignore_standard_quota_account_ids=inputs.ignore_standard_quota_account_ids,
        soft_drain_enabled=False,
        log_weight_transitions=False,
    )
    all_exhausted = bool(states) and all(
        state.subscription_exhausted and not state.ignore_standard_quota for state in states
    )
    allowed_ids = {
        state.account_id
        for state in states
        if not state.subscription_exhausted
        or state.ignore_standard_quota
        or (all_exhausted and state.has_usable_credits)
    }
    return replace(inputs, accounts=[account for account in inputs.accounts if account.id in allowed_ids])


async def account_allowed(
    balancer: LoadBalancer,
    account_id: str,
    *,
    model: str | None,
    service_tier: str | None = None,
    account_ids: Collection[str] | None = None,
    require_security_work_authorized: bool = False,
) -> bool:
    # Use the same state builder as normal selection without importing its owner
    # module at initialization (LoadBalancer imports the pure funding filter).
    from app.modules.proxy.load_balancer import _build_states

    inputs = await balancer._load_selection_inputs(model=model, service_tier=service_tier, account_ids=account_ids)
    if require_security_work_authorized:
        inputs = replace(inputs, accounts=[account for account in inputs.accounts if account.security_work_authorized])
    allowed = filter_funding_inputs(inputs, now=balancer._clock.time(), build_states=_build_states)
    return any(account.id == account_id for account in allowed.accounts)


class QuotaFirstStickySelectionMixin:
    _quota_first_lock: asyncio.Lock
    _fresh_thread_allocations: dict[str, int]
    _runtime: dict[str, RuntimeState]
    _clock: Clock

    async def _select_with_stickiness(
        self,
        *,
        states: list[AccountState],
        account_map: dict[str, Account],
        sticky_key: str | None,
        sticky_kind: StickySessionKind | None,
        reallocate_sticky: bool,
        sticky_max_age_seconds: int | None,
        budget_threshold_pct: float = 95.0,
        secondary_budget_threshold_pct: float = 100.0,
        prefer_earlier_reset_accounts: bool,
        prefer_earlier_reset_window: ResetPreferenceWindow,
        routing_strategy: RoutingStrategy,
        relative_availability_power: float = 2.0,
        relative_availability_top_k: int = 5,
        sticky_repo: StickySessionsRepository | None,
        routing_costs_by_account_id: RoutingCostsByAccount | None = None,
        sticky_existing_account_id: str | None | object = _STICKY_EXISTING_UNSET,
        initial_preferred_account_id: str | None = None,
        allow_burn_first_reallocation: bool = False,
        preserve_existing_mapping_on_fallback: bool = False,
        preserve_reason_request_local: bool = False,
        traffic_class: TrafficClass = TRAFFIC_CLASS_FOREGROUND,
        ignore_standard_quota: bool = False,
        allow_usage_exhaustion_error: bool = True,
        usage_exhaustion_states: Iterable[AccountState] | None = None,
        sticky_refresh_skip_deadline: datetime | None = None,
        hard_owner_pool: bool = False,
        redact_sensitive_details: bool = False,
    ) -> _StickySelectionOutcome:
        balanced = routing_strategy == "quota_first_balanced"
        async with self._quota_first_lock if balanced else nullcontext():
            if balanced:
                for state in states:
                    state.fresh_thread_allocations = self._fresh_thread_allocations.get(state.account_id, 0)
            outcome = await _run_select_with_stickiness(
                states=states,
                account_map=account_map,
                sticky_key=sticky_key,
                sticky_kind=sticky_kind,
                reallocate_sticky=reallocate_sticky,
                sticky_max_age_seconds=sticky_max_age_seconds,
                budget_threshold_pct=budget_threshold_pct,
                secondary_budget_threshold_pct=secondary_budget_threshold_pct,
                prefer_earlier_reset_accounts=prefer_earlier_reset_accounts,
                prefer_earlier_reset_window=prefer_earlier_reset_window,
                routing_strategy=routing_strategy,
                relative_availability_power=relative_availability_power,
                relative_availability_top_k=relative_availability_top_k,
                sticky_repo=sticky_repo,
                routing_costs_by_account_id=routing_costs_by_account_id,
                sticky_existing_account_id=sticky_existing_account_id,
                initial_preferred_account_id=initial_preferred_account_id,
                allow_burn_first_reallocation=allow_burn_first_reallocation,
                preserve_existing_mapping_on_fallback=preserve_existing_mapping_on_fallback,
                preserve_reason_request_local=preserve_reason_request_local,
                traffic_class=traffic_class,
                ignore_standard_quota=ignore_standard_quota,
                allow_usage_exhaustion_error=allow_usage_exhaustion_error,
                usage_exhaustion_states=usage_exhaustion_states,
                sticky_refresh_skip_deadline=sticky_refresh_skip_deadline,
                hard_owner_pool=hard_owner_pool,
                overload_backoff_runtime=self._runtime,
                clock=self._clock,
                redact_sensitive_details=redact_sensitive_details,
            )

            selected = outcome.selection.account
            if (
                balanced
                and selected is not None
                and not isinstance(sticky_existing_account_id, str)
                and not hard_owner_pool
            ):
                self._fresh_thread_allocations[selected.account_id] = selected.fresh_thread_allocations + 1
            return outcome
