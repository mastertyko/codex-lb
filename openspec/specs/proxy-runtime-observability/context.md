# Proxy Runtime Observability Context

## Purpose and Scope

This capability defines what operators should be able to see in the live server console while debugging proxy traffic.

See `openspec/specs/proxy-runtime-observability/spec.md` for normative requirements.

## Decisions

- **Timestamps are always on:** timestamped console logs are a baseline operator need, not a debug-only feature.
- **Request tracing is opt-in:** outbound request summary and payload tracing remain configurable because payload logs can be noisy or sensitive.
- **Error logs must be correlated:** request id, endpoint, status, code, and message are the minimum useful fields for debugging 4xx/5xx failures.

## Operational Notes

- Use request ids to correlate inbound proxy logs, outbound upstream traces, and client-visible failures.
- Prefer summary tracing in normal debugging sessions; enable payload tracing only when the exact normalized outbound request matters.
- For direct compact `5xx` failures, look for `proxy_compact_failure` alongside `upstream_request_complete`; together they show the compact failure phase, failure detail, exception type, retry metadata, and affinity source.

## Activity State Endpoint

### Purpose and Non-Goals

`GET /api/activity/state` supports a local host poller that needs one bounded, privacy-safe activity signal without dashboard credentials. It is intentionally an aggregate-only read model, not a request inspector, account monitor, billing endpoint, or replacement for authenticated dashboard APIs.

### Decisions and Constraints

- The service queries only the requested recent window, excludes warmup traffic at the repository layer, and clamps the caller's window to 10–3600 seconds.
- Cached input is a subset of input, so scoring subtracts cached tokens before applying the discounted cached-input weight. The strongest non-error signal owns 85% of the score and error pressure owns 15%, allowing a fully saturated workload to reach exactly `1.0`.
- The endpoint is credentialless so a local host process can poll it, which makes the response's fixed aggregate schema and explicit exclusion of identifiers, model names, prompts, response bodies, and error detail a security boundary.
- Repository failures return the last successful aggregate with `sourceStatus=stale` when one exists; without a prior success they return a zero-valued stale response. A successful empty query reports `sourceStatus=live`, distinguishing idle from unavailable storage.

### Example

A poll with `windowSeconds=120` may return `activity=0.37`, `sourceStatus=live`, request/error counts, aggregate token totals, aggregate cost, and generated/since timestamps. It never returns which request, account, key, model, prompt, or error produced those totals.

### Operational Notes

The host poller should treat `sourceStatus=stale` as degraded telemetry and use `generatedAt` plus `since` to judge freshness. The endpoint's 200 response is deliberate for both live-idle and stale fallback states so transient request-log storage failures do not turn the poller itself into load or an availability dependency.

## Direct-WebSocket Archive Attribution

Inbound archive attribution follows the same parsed frame and pending-request choice used for downstream response ownership. A malformed `response.created` frame with no string response id is kept unattributed rather than guessed onto the first pending request; this prevents audit records from claiming a conversation owner that the relay could not establish.
