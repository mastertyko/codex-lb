## Why

The direct Responses WebSocket relay repeatedly decoded and model-parsed every upstream text frame and forced multiple scheduler checkpoints per frame, measuring 77,331 ns per event in a deterministic multiplexed workload. Its archive matcher could also attribute a malformed `response.created` frame without a response id to a pending request even though the downstream relay would not match that frame.

## What Changes

- Parse each upstream WebSocket text frame once and share the parsed payload between archive attribution and downstream processing.
- Build typed OpenAI event models only for terminal events that consume typed usage or error fields.
- Match archive ownership from an event-loop-local snapshot without a redundant lock acquisition, while keeping malformed `response.created` frames without response ids unattributed.
- Use fast uncontended WebSocket locks with a bounded relay checkpoint, preserving waiter fairness, cancellation behavior, multiplexed frame order, and archive attribution.
- Add a deterministic direct-WebSocket relay benchmark with fixed correctness, contention, cancellation, and ready-enqueue fairness contracts plus median and p95 nanoseconds per event.

## Capabilities

### New Capabilities

- `proxy-relay-performance`: Measurable direct-WebSocket relay performance with deterministic correctness and scheduler-fairness gates.

### Modified Capabilities

- `proxy-runtime-observability`: Conversation archive attribution must agree with direct-WebSocket response matching, including malformed created frames.

## Impact

- Affects the direct Responses WebSocket relay and archive matcher in `app/modules/proxy/_service/websocket/mixin.py`.
- Adds `scripts/benchmark_websocket_relay.py` and focused archive-attribution regression coverage.
- Does not change public routes, downstream frame schemas, configuration, or dependencies.
