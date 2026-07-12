## Why

Separately metered Codex models can remain usable through fresh per-account quota telemetry even when the general upstream model catalog omits them. `codex-lb` currently treats that catalog omission as definitive account-level non-support and rejects `gpt-5.3-codex-spark` with `no_plan_support_for_model` before evaluating fresh Spark quota data.

## What Changes

- Allow fresh additional-quota telemetry to provide account-specific eligibility evidence for a mapped, separately metered model when the general per-account catalog omits that model.
- Preserve model plan and service-tier filtering before additional-quota availability, exhaustion, health, cooldown, and routing gates are evaluated.
- Add regression coverage for an authoritative account catalog that omits Spark while a plan-compatible account has fresh, available Spark quota data.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `model-catalog-compat`: Define how routing reconciles authoritative general account catalogs with fresh account-specific additional-quota evidence for separately metered models.

## Impact

- Account candidate filtering in `app/modules/proxy/load_balancer.py`.
- Spark and future separately metered model routing that uses the additional-quota registry.
- Focused load-balancer regression coverage; no API schema or database migration changes.
