## Why

Request-log serialization rounds positive estimates below USD 0.0000005 to zero before the dashboard can show its less-than indicator. The dashboard also needs to explain which service tier supplies an estimate, particularly when requested Ultrafast differs from the upstream-reported tier.

## What Changes

- Preserve unrounded request cost values through the API and round only for display.
- Identify the recorded pricing tier, requested tier, upstream tier and estimate basis in request details, with a compact pricing-tier label in the table.
- Mark requested-tier estimates as unconfirmed, missing tier information as unknown, and independently rounded breakdowns as approximate.
- Preserve saved costs, current pricing and subscription routing behavior.

## Capabilities

### Modified Capabilities
- `proxy-runtime-observability`: precise request-cost serialization and explicit price-tier presentation.

## Impact

Request-log mapper, cost-breakdown comparison, dashboard presentation and localized strings. No schema migration, pricing refresh, backfill or routing change.
