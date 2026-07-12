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

For a model mapped by the additional-quota registry, account candidate filtering resolves the authoritative general per-account model index independently from requested service-tier filtering. Accounts present in that general model index stay in the normal pool only when they also pass the authoritative per-account service-tier index. Only accounts genuinely absent from the general model index may use the omission fallback, which applies the registry's allowed plan or service-tier plans before requiring fresh model-specific quota telemetry.

This keeps the exception narrow and evidence-backed. A catalog-supported account rejected by the requested account-level service tier cannot be reclassified as model-catalog-omitted or restored by quota evidence. Treating bootstrap metadata as globally authoritative would reject genuinely omitted-but-usable models, while bypassing every model or tier filter would admit unsupported accounts.

Explicit caller-supplied additional-limit filters do not activate this exception. Only a canonical model-to-quota mapping can override the general account catalog, preventing an unrelated quota key from bypassing model support.

## Risks / Trade-offs

- A malformed additional-quota registry could map a model incorrectly. Existing canonical registry loading, plan applicability, and fresh-data requirements constrain that risk.
- Service-tier account affinity is less precise only for an account genuinely omitted from the general model catalog, because no model-specific account-tier entry exists to trust for that account. Plan-level service-tier filtering remains authoritative for that fallback; catalog-supported accounts continue to require the exact per-account service-tier index.
- Fresh quota telemetry may temporarily disappear during refresh failures. Selection remains fail-closed with the existing additional-quota data-unavailable error.
