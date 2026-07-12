## Context

The direct Responses WebSocket reader handled each upstream text frame in two separate paths: archive ownership and downstream relay processing. The two paths independently built SSE wrappers, decoded JSON, and built typed `OpenAIEvent` models; downstream tool-call rewriting then parsed the same event again. A deterministic workload with eight multiplexed requests and 64 text deltas per request measured 77,331 ns per event. Profiling 8,576 text frames recorded 42,880 `parse_sse_data_json` calls, 25,728 `parse_sse_event` calls, 4,072,901 total function calls, and 1.516 seconds of profiled execution.

The relay also acquired AnyIO locks multiple times per frame. AnyIO's default uncontended acquisition includes a scheduler checkpoint for fairness. That is safe but expensive in this loop, and removing every checkpoint would let a prebuffered upstream burst starve a ready request-enqueue task. Archive attribution has a separate correctness constraint: it must select the same owner as the downstream relay, and malformed `response.created` frames without response ids must remain unattributed.

## Goals / Non-Goals

**Goals:**

- Decode each upstream WebSocket text frame once and share the result between archive and relay paths.
- Avoid typed event-model construction for non-terminal frames that use only dictionary fields.
- Remove redundant uncontended scheduling overhead while preserving bounded fairness, waiter cancellation, frame order, and archive ownership.
- Provide a reproducible benchmark that makes performance changes measurable and rejects correctness drift.

**Non-Goals:**

- Change public WebSocket routes, frame schemas, retry policy, continuity semantics, or account routing.
- Change HTTP-bridge lock policy or optimize unrelated proxy paths in this change.
- Introduce a new JSON library, dependency, database migration, or configuration setting.

## Decisions

### Share one parsed-frame value

The relay parses raw WebSocket JSON directly into a slotted immutable parsed-frame value before archive attribution. The same object carries rewritten text, payload, event type, and an optional typed event into downstream processing. This removes duplicate JSON and SSE parsing without copying the payload.

Typed `OpenAIEvent` validation runs only for `response.completed`, `response.failed`, `response.incomplete`, and `error`, because only terminal handling consumes typed usage or error models. Non-terminal matching, service-tier extraction, tool-call handling, sequence tracking, and response-id lookup continue to use the parsed dictionary.

Alternative: retain separate parsers and only skip one model parse. Rejected because profiling showed five JSON decodes and three event parses per text frame across the two paths.

### Match archive ownership from an event-loop-local snapshot

Archive matching is synchronous after `upstream.receive()` and before the relay's next await. Pending-request mutations are event-loop-local and their lock-protected mutation blocks contain no await, so the read-only snapshot cannot observe a partially mutated deque. This removes a redundant lock acquisition while retaining the lock for all mutations and downstream state transitions.

For `response.created`, archive matching requires a string response id before it may select an unassigned pending request. This explicitly keeps malformed created frames unattributed and aligns archive behavior with downstream response-id assignment.

Alternative: move archival after downstream processing and reuse that lock acquisition. Rejected because a processing failure could prevent diagnostic archival and would reorder archive side effects.

### Keep AnyIO locks and use bounded fairness checkpoints

The direct WebSocket session keeps AnyIO locks but enables `fast_acquire` for its pending-state and downstream-send locks. This preserves AnyIO's waiter queue and cancellation behavior while avoiding an unconditional checkpoint on every uncontended acquisition.

The reader yields before its first handled frame and then once every 32 received frames. The checkpoint occurs after receive and before parsing or archive attribution, so a frame is never partially matched across the yield. This bounds starvation for a task that becomes ready during a prebuffered burst while avoiding two forced yields per event.

Alternative: replace AnyIO locks with `asyncio.Lock`. Rejected because it widens the type and behavioral cutover without improving the measured fast path materially. Alternative: remove all checkpoints. Rejected because a ready enqueue task could remain unscheduled until an immediately available burst drained.

### Benchmark the real relay with fixed contracts

`scripts/benchmark_websocket_relay.py` invokes the real direct-WebSocket relay and processor with eight multiplexed requests, 64 deltas each, archive capture, terminal cleanup, a fast fake downstream, and a prebuffered fake upstream. It reports median and p95 nanoseconds per event over 21 samples after warmup.

The correctness digest covers downstream bytes and order, response ownership, archive attribution, malformed-created behavior, contended pending/send lock waiters, cancellation while waiting, and a ready enqueue marker that must run before the burst drains. The benchmark patches persistence and account-health side effects only; it does not replace relay parsing, matching, locking, or downstream emission.

## Risks / Trade-offs

- Fast uncontended locks could monopolize the event loop during buffered bursts -> yield before the first frame and every 32 frames; assert a ready enqueue runs before full drain.
- Lazy typed parsing could omit terminal usage or error data -> use one terminal-event constant for parsing, pending removal, and finalization boundaries; run the full direct-WebSocket integration suite.
- Synchronous archive matching could become unsafe if pending mutations gain awaits or move across threads -> document the no-await event-loop invariant and keep every mutation lock-protected.
- Shared parsed state could make archive and downstream ownership drift together unnoticed -> validate exact per-response archive ids independently in multiplexed and malformed-created cases.
- The benchmark uses synthetic in-memory I/O -> report per-event CPU/scheduler cost, not network latency or end-to-end TTFT.

## Migration Plan

1. Deploy the relay implementation and benchmark together; no data or configuration migration is required.
2. Run the deterministic benchmark, direct-WebSocket integration suite, proxy utility suite, lint, and type checks before release.
3. Roll back by reverting the shared parser, fast-lock construction, and periodic checkpoint as one code change; archived data and persisted request logs require no repair.

## Open Questions

None.
