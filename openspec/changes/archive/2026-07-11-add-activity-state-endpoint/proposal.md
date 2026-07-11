## Why

Local display integrations need a stable, privacy-preserving signal for whether `codex-lb` is currently doing work. The existing activity daemon polls `/api/activity/state`; when the endpoint is missing, it emits a 404 every two seconds and cannot reflect real proxy activity.

## What Changes

- Add a read-only activity-state endpoint derived from existing warmup-excluded request-log aggregates.
- Return only low-cardinality counters plus a normalized `activity` value.
- Clamp the aggregation window to a bounded range and report reachable-but-idle runtimes as `activity = 0.0`.
- Keep the response free of request ids, account ids, API keys, model names, prompts, response text, error messages, and other per-request correlation data.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `proxy-runtime-observability`: Define the privacy, bounded-query, response-shape, and idle-state requirements for the activity-state endpoint.

## Impact

- Backend: adds an `activity` API module and request-scoped dependency context backed by the existing request-log repository.
- API: adds `GET /api/activity/state?windowSeconds=<seconds>`.
- Tests: adds endpoint contract, aggregation, clamping, scoring, and sensitive-data exclusion coverage.
- Operations: restores the contract used by the host-side `codex-activityd` poller without exposing detailed dashboard telemetry.
