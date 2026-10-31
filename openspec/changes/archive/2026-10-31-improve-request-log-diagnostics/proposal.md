## Why

Request logs hide known request types and useful diagnostic metadata, while compaction and warmup omit actual upstream transport. Operators cannot reliably isolate these calls or distinguish a small estimated cost from zero.

## What Changes

- Label known request types and add request-kind, downstream-transport, and upstream-transport filters with URL persistence and consistent result totals.
- Make request type and transport searchable, including the displayed Web search name.
- Record actual upstream HTTP attempts for compaction and warmup while leaving pre-dispatch failures unknown.
- Expose existing phase timings and render existing error metadata in request details.
- Preserve small positive cost estimates in the table and show more precision in details.
- Investigate missing TTFT independently; change first-token detection only if a specific failing event path is demonstrated.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `proxy-runtime-observability`: Request-log classification, filtering, transport provenance, diagnostic details, timing visibility, and estimated-cost presentation.

## Impact

Request-log API/service/repository, proxy compaction and warmup logging, dashboard schemas/filters/details, locales, and focused regression tests. Existing nullable database columns are reused; no migration, authentication, routing, pricing, or settlement-policy change is intended. Existing Web search work and private runtime customizations must be retained.
