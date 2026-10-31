## Context

See proposal.md. Request logs already persist kinds, transport, error metadata and several timing phases. The existing count fast path uses aggregates without transport dimensions, and counts have a process-local cache. The active worktree contains the completed Web search fix, while production also has unrelated private adaptations.

## Goals / Non-Goals

Expose the existing facts and fix omitted transport provenance. Preserve prior Web search behavior and null semantics. No new database column, route policy, permission, retry policy, dependency, or configuration is required. TTFT investigation must not infer generation timing from a control event.

## Decisions

- Add optional filters through route, service, repository and frontend URL state. Include them in count-cache identity and use the raw filtered count when the existing aggregate lacks the selected dimension. Apply them to existing facets as well.
- Use the established multi-select controls and one shared localized request-kind label mapping. Keep model identity visible beside non-normal labels; Web search keeps its dedicated model label.
- Set compaction/warmup upstream transport at the client invocation boundary, after account/token/route preparation. Do not backfill historical transport.
- Expose the four existing phase columns directly. Show diagnostics only when there is data; keep explicit zeroes and display unknown measurements as unavailable.
- Limit additional cost precision to request-log details. The compact table uses a less-than-cent indication when its ordinary formatter would round to zero.
- Analyze missing TTFT using bounded event metadata where available. A separate confirmed regression is required before modifying first-token detection.

## Risks / Trade-offs

- Filtered totals can leak unfiltered cached counts or use incompatible aggregates → regression tests combine pagination, successive filter values, status and legacy kinds.
- Runtime overlays differ from upstream → apply a narrow verified patch to captured live files and reproduce the production frontend before rebuilding.
- Sensitive operational metadata → preserve current authorization and redaction boundaries; no additional request payload or credential capture.

## Migration Plan

Ship API and frontend together after focused route/component/browser checks. Use the existing image-only cutover and retain the prior image as rollback. Database schema and historical rows remain unchanged.
