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

### Purpose and Scope

`GET /api/activity/state` supplies a coarse recent-activity signal to local display integrations such as `codex-activityd`. The normative privacy, scoring, window, and anonymous-access contract is in `spec.md` under **Privacy-safe activity state endpoint**. This surface is not a replacement for authenticated request-log or dashboard telemetry.

### Decisions and Constraints

- Reuse the existing warmup-excluded request-log aggregate query; do not persist a second activity history or inspect prompt/response payloads.
- Keep the poller credentialless. Network reachability remains the access boundary, while the response is restricted to low-cardinality aggregate counters and timestamps.
- Treat cached input as a subset of input tokens: remove it from uncached input before adding it back at 25% weight.
- Let the strongest request, weighted-token, or cost signal contribute 85% of the score and error pressure contribute 15%. This keeps `1.0` reachable without summing correlated usage signals.

### Failure Modes

- A missing route produces repeated `404` responses and causes the display daemon to decay toward idle; it does not indicate a proxy transport failure.
- A database/query failure remains an HTTP error. The server must not fabricate a successful idle response, because that would make unavailable telemetry indistinguishable from real inactivity.
- The score reflects recently persisted request logs, so newly started in-flight work can appear after a short delay.

### Example

```http
GET /api/activity/state?windowSeconds=10
```

```json
{
  "activity": 0.578,
  "stale": false,
  "source": "codex-lb",
  "sourceStatus": "ok",
  "generatedAt": "2026-07-11T03:30:00Z",
  "since": "2026-07-11T03:29:50Z",
  "windowSeconds": 10,
  "requestCount": 1,
  "errorCount": 0,
  "inputTokens": 1200,
  "outputTokens": 240,
  "cachedInputTokens": 800,
  "costUsd": 0.01
}
```

### Operational Notes

The local daemon normally polls every two seconds with a 10-second window. Sustained `dashboard_error_response ... path=/api/activity/state status=404` logs mean the deployed backend lacks the contract; verify the image revision and route registration before investigating browser cache or WebSocket health.
