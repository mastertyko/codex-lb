## Context

The model registry aggregates general per-plan and per-account Codex catalogs. Some separately metered models, including `gpt-5.3-codex-spark`, can be omitted from that general per-account catalog while active accounts continue to report fresh model-specific additional-quota telemetry. Account selection currently applies the exact per-account catalog filter before loading additional-quota data, so an authoritative empty account index rejects the request before stronger model-specific evidence is evaluated.

## Goals / Non-Goals

**Goals:**
- Let fresh model-specific additional-quota telemetry establish account-level support for mapped, separately metered models.
- Preserve registry plan and service-tier restrictions.
- Preserve fail-closed behavior for stale, missing, or exhausted additional-quota data and all existing health, cooldown, capacity, and routing gates.

**Non-Goals:**
- Do not add a generic fallback for unknown or unmapped models.
- Do not change model discovery endpoints or reinsert Spark into an authoritative general catalog.
- Do not change quota persistence, refresh cadence, or API schemas.

## Decisions

For a model mapped by the additional-quota registry, account candidate filtering skips only the registry's exact per-account model index. It still evaluates the registry's allowed plan or service-tier plans. The existing additional-quota filter then requires fresh account-specific telemetry and rejects missing, stale, or exhausted quota data before routing.

This keeps the exception narrow and evidence-backed. Treating the bootstrap catalog as globally authoritative would resurrect models without current account evidence; bypassing every model filter would admit plans that do not support the model. Deferring only exact account support to fresh additional-quota telemetry avoids both failures.

Explicit caller-supplied additional-limit filters do not activate this exception. Only a canonical model-to-quota mapping can override the general account catalog, preventing an unrelated quota key from bypassing model support.

## Risks / Trade-offs

- A malformed additional-quota registry could map a model incorrectly. Existing canonical registry loading, plan applicability, and fresh-data requirements constrain that risk.
- Service-tier account affinity is less precise for a mapped additional-quota model omitted from the account catalog; plan-level service-tier filtering remains enforced and the subsequent quota/health gates remain authoritative.
- Fresh quota telemetry may temporarily disappear during refresh failures. Selection remains fail-closed with the existing additional-quota data-unavailable error.
