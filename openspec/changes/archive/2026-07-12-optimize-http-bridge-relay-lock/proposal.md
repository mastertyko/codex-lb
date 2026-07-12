## Why

The HTTP Responses bridge relay pays AnyIO's fairness checkpoint on every uncontended pending-request lock acquisition, even though frame receive and queue fan-out already define explicit scheduling boundaries. In the deterministic relay workload, an isolated fast-acquire experiment reduced median cost from approximately 79,241 to 18,095 ns per event, but the cutover needs bounded fairness and contended cancellation proof before it is safe.

## What Changes

- Enable fast uncontended acquisition for the HTTP-bridge session's pending-request lock.
- Add a bounded scheduler checkpoint at a completed-frame boundary so a ready request enqueue cannot be starved by a prebuffered upstream burst.
- Extend the real HTTP-bridge relay benchmark with concurrent writer/reader contention, cancellation while waiting, ready-enqueue fairness, exact archive attribution, frame order, terminal sentinel, and cleanup contracts.
- Preserve HTTP response bodies, SSE order, request ownership, timeout behavior, and public configuration.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `proxy-relay-performance`: Extend measurable bounded-fairness and cancellation requirements to the persistent HTTP Responses bridge relay.

## Impact

- Affects HTTP-bridge session lock construction and upstream relay scheduling in `app/modules/proxy/_service/http_bridge/`.
- Extends `scripts/benchmark_http_bridge_relay.py` and focused bridge lifecycle coverage.
- Does not change public routes, downstream schemas, dependencies, or persisted data.
