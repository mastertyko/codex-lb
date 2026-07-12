## Why

A production canary of the optimized persistent HTTP bridge showed an elevated `stream_incomplete` rate, including local session-close failures that the current request-log fields cannot attribute to a finite close cause. The optimization is not proven causal, so the safest release candidate restores the pre-optimization bridge runtime as one coherent bundle while retaining deterministic measurement and adding failure-only attribution for the next canary.

The release-candidate scope also covers the shared pending-request cleanup used by persistent HTTP-to-WebSocket bridging and direct downstream WebSockets: reservation-first settlement ordering, draining and initially-unsettled health neutrality, bounded partial-release retry, foreground cancellation ownership transfer, exactly-once finalization, and shutdown cancellation to transitive cleanup quiescence.

The integration base is the upstream `v1.21.0-beta.3` release commit `a225f0db0c3e00224d3f4256590d5d05dfa763d4`. That release already retains the pre-`f787f10c` HTTP bridge scheduling bundle and adds admission-waiter recovery, isolated unanchored lanes, reconnect affinity, incomplete-reason fidelity, safe owner replay, and sequenced-replay refusal. This change therefore preserves those upstream implementations and reapplies only non-duplicated measured performance and cleanup semantics.

## What Changes

- Preserve beta.3's default pending lock, `asyncio.wait_for` receive and queue waits, eager HTTP event parsing, response/error derivation, awaited queue puts, and relay scheduling unchanged; keep the prior HTTP scheduling optimization excluded pending a separate reviewed canary.
- Keep the eager HTTP `rewrite_parallel_tool_call_text` contract and remove no beta.3 API that still has a production caller.
- Retain and rebaseline the deterministic HTTP-bridge benchmark against beta.3 production semantics without weakening routing, ownership, archive attribution, order, cancellation, contention, timeout, sentinel, or cleanup contracts and without requiring a scheduler yield during a finite prebuffered burst.
- Record a finite local bridge-close reason and whether each failed request was already draining in the existing `failure_phase` and `failure_detail` fields, without suppressing `stream_incomplete` or changing persisted schemas.
- Preserve the current live stale-diagnostic behavior and add regression coverage for draining idle-prune and non-draining close attribution.
- Preserve shared HTTP/direct-WebSocket reservation settlement before account health, exclude draining or initially-unsettled cleanup from health penalties, batch partial-release retries, retain post-take ownership across foreground cancellation, and make shutdown cancellation await exactly-once finalizers and all repository-using cleanup.
- Reapply the measured direct-WebSocket parse-once and bounded-fairness relay path against beta.3 while preserving reconnect affinity, incomplete reasons, safe replay ownership, and sequenced-replay refusal.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `proxy-relay-performance`: Preserve the beta.3 HTTP bridge runtime baseline, restore only non-duplicated measured hot paths, and retain deterministic correctness and performance measurement for HTTP and direct-WebSocket relays.
- `proxy-runtime-observability`: Require failure-only HTTP bridge close attribution plus shared HTTP/direct-WebSocket settlement ordering, health neutrality, partial-failure ownership, exactly-once finalization, unusable-upstream retirement before terminal publication, and shutdown cleanup quiescence.

## Impact

- Affects measured core, usage, direct-WebSocket, and persistent HTTP bridge paths; HTTP-specific close callsites; shared direct-WebSocket cleanup; cancel-safe task ownership; request-log persistence ownership; deterministic benchmark scripts; and reconciled OpenSpec artifacts.
- Preserves beta.3 bridge admission, unanchored-lane isolation, turn-state and durable affinity, safe replay, sequence, incomplete-reason, version, migration, dependency, and unrelated release behavior.
- Adds no route, response-schema, database-schema, migration, dependency, configuration, or version rollback.
- Leaves local `main`, prior branches, live services, image artifacts, and remote refs unchanged.
