## Why

A stalled upstream HTTP bridge request can keep a session's `response_create_gate` locked indefinitely when any pre-`response.created` upstream event has already arrived. Later requests to the same sticky session repeatedly fail with local overload instead of replacing the stale bridge.

## What Changes

- Retire an HTTP bridge session when its gate holder remains pre-`response.created` and makes no upstream progress for the configured stale-gate interval.
- Preserve active long-running turns by measuring inactivity rather than total request age.
- Preserve generation safety by replacing the stale bridge session and keeping late cleanup bound to the old session's semaphore.
- Add regression coverage for silent holders, one-event-then-stalled holders, and continuously progressing holders.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `proxy-admission-control`: Define inactivity-based recovery for stalled per-session response-create gates.
- `proxy-runtime-observability`: Require low-cardinality retirement diagnostics for inactivity-triggered recovery.

## Impact

- Affected code: HTTP bridge request state progress tracking and response-create gate timeout recovery.
- Affected tests: focused HTTP bridge gate and upstream-event lifecycle tests.
- Operational behavior: later requests can recover from a stale sticky bridge without restarting codex-lb; healthy active streams remain untouched.
