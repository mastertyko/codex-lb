## Context

The per-session HTTP bridge gate is released only after `response.created` or terminal cleanup. The current timeout recovery treats a holder as stale only when no upstream event has ever arrived, so one heartbeat followed by silence can wedge the sticky session indefinitely. Session replacement is already generation-safe: each bridge object owns its semaphore and registry removal is guarded by object identity.

## Goals / Non-Goals

**Goals:**
- Recover a sticky HTTP bridge after its pre-`response.created` holder stops making upstream progress.
- Keep actively progressing requests alive even when their total age exceeds the stale threshold.
- Reuse existing bridge replacement and old-generation cleanup semantics.

**Non-Goals:**
- Change global or account concurrency limits.
- Add retries for arbitrary upstream failures.
- Apply HTTP bridge retirement to direct WebSocket connections.

## Decisions

Track a monotonic `last_upstream_progress_at` timestamp on each request state. Initialize stale-age calculation from `started_at`; update the timestamp whenever the bridge matches an upstream event to that request. On a later gate-acquisition timeout, retire the bridge only when the holder is still awaiting `response.created`, has no downstream-visible output, and has made no progress for the configured stale-gate interval.

Use the existing whole-session retirement path rather than forcibly releasing the semaphore. The old request retains the old bridge semaphore, while a replacement bridge receives a new semaphore; late cleanup therefore cannot release the new generation.

Do not use total request age after the first event. Long-running but active startup sequences may legitimately exceed the threshold and must survive while events continue.

## Risks / Trade-offs

- An upstream event exactly at the threshold can race with timeout inspection; the bridge pending lock serializes event matching and the progress snapshot used by retirement.
- An upstream that emits meaningless events forever prevents retirement. This is intentional: the fix defines staleness as no progress, avoiding speculative event classification.
- The waiting request still receives the bounded local timeout; recovery applies to subsequent requests, preserving the existing public error contract.
