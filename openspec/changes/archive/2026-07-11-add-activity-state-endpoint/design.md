## Context

A host-side `codex-activityd` process polls `GET /api/activity/state?windowSeconds=10` every two seconds to drive a local activity display. The endpoint was implemented previously but was lost when local work was integrated with upstream `v1.21.0-beta.1`; the daemon therefore receives continuous 404 responses. Request logs already provide warmup-excluded aggregate counts, tokens, errors, and cost, so no new persistence model is required.

The endpoint is intentionally low-cardinality and read-only. It must remain useful to a local unauthenticated poller without exposing request-, account-, model-, or prompt-level data.

## Goals / Non-Goals

**Goals:**

- Restore the activity-state contract consumed by `codex-activityd`.
- Derive activity from the existing `RequestLogsRepository.aggregate_activity_since` query.
- Return a deterministic score in the inclusive range `[0.0, 1.0]` and enough aggregate counters to diagnose the score.
- Bound query cost by clamping the requested window to 10–3600 seconds.
- Preserve privacy by exposing no identifiers, payload content, model names, or error details.

**Non-Goals:**

- Add request-level telemetry or another request-log endpoint.
- Persist a separate activity history or cache.
- Add active/idle process tracking outside request logs.
- Change the dashboard authentication model or introduce a daemon credential.

## Decisions

### Reuse the request-log aggregate repository

Add an `activity` module with the existing API/service/schema separation and construct it from the request-scoped `RequestLogsRepository`. This keeps request-log filtering—especially warmup exclusion—in one query path and avoids duplicating SQL or introducing a background sampler.

Alternative: infer activity from live proxy task state. Rejected because it would miss recently completed requests, require cross-worker coordination, and create a second source of truth.

### Clamp rather than reject the requested window

Use a 120-second default and clamp `windowSeconds` to 10–3600 seconds. A daemon can request its short 10-second window, while malformed or oversized values cannot trigger unbounded aggregation work. Clamping preserves a usable response for simple pollers.

Alternative: FastAPI validation with `ge`/`le`. Rejected because a stale client would receive another error loop rather than a safe bounded result.

### Compute a bounded low-cardinality score

The service combines request count, logarithmically scaled billable-weighted tokens, cost, and error count. Because `input_tokens` already includes cached input, the cached subset is first removed from uncached input and then reintroduced at 25% weight. The strongest normalized request/token/cost signal contributes 85% of the score and capped error pressure contributes 15%, so fully saturated inputs can reach `1.0`. The final score is capped at `1.0`, rounded to four decimals, and exactly `0.0` when all aggregates are zero.

Alternative: request count alone. Rejected because one long, token-heavy request should produce visible activity even when request volume is low.

### Return aggregate status only

The schema exposes source/status timestamps, the effective window, aggregate counters, cost, and activity. It excludes request ids, account ids, API keys, model names, prompts, response text, error messages, and top-error values. `stale=false` and `sourceStatus=ok` mean the server completed the live database query; transport failures remain ordinary HTTP errors rather than fabricated idle responses.

Alternative: reuse the detailed dashboard summary. Rejected because that surface contains more data than the display needs and couples the daemon to operator-facing contracts.

## Risks / Trade-offs

- The endpoint reveals coarse service activity to any caller that can reach the server. Mitigation: expose only bounded aggregates with no correlation identifiers or content; deployment access controls remain the network boundary.
- Every poll performs an aggregate database query. Mitigation: clamp the window and reuse the indexed request-log path; the current two-second single-client cadence is bounded.
- The score is heuristic rather than a utilization metric. Mitigation: keep it normalized, deterministic, monotonic for each positive component, and document exact implementation constants in code/tests.
- Activity derived from request logs trails in-flight work until a log row exists. This is accepted because the display contract is recent activity, not exact task scheduling state.
