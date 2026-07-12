## Context

The persistent HTTP Responses bridge uses one `anyio.Lock` to protect its pending-request deque and queued-request count. The upstream reader, request submission path, timeout cleanup, cancellation cleanup, and session retirement all coordinate through that lock. AnyIO's default uncontended acquire performs a cancellation-safe scheduler checkpoint; the relay acquires the lock while matching every upstream text frame, so the checkpoint dominates the in-memory relay benchmark after the parse and queue hot paths were optimized.

An isolated benchmark substitution measured approximately 79,241 ns per event with the default lock and 18,095 ns per event with `fast_acquire=True`. That substitution alone is unsafe evidence: a prebuffered fake upstream and unbounded downstream queues can complete without yielding, allowing the reader to drain a burst before a newly ready request-enqueue task is scheduled. A checkpoint placed after receive but before attribution is also unsafe because a request that was not in flight when the frame arrived could participate in matching.

## Goals / Non-Goals

**Goals:**

- Remove the unconditional scheduler checkpoint from uncontended HTTP-bridge pending-lock acquisition.
- Preserve waiter order, cancellation, request ownership, archive attribution, SSE order, terminal sentinels, timeout cleanup, and session retirement.
- Bound reader-loop starvation without yielding between frame receipt and archive/match/downstream processing.
- Extend the deterministic benchmark so the lock policy cannot pass through event-loop monopolization.

**Non-Goals:**

- Replace AnyIO locks with `asyncio.Lock`.
- Change lifecycle or prewarm lock policy.
- Change bridge admission, routing, retry, timeout, or downstream response contracts.
- Optimize direct-WebSocket relay behavior in this change.

## Decisions

### Enable fast acquisition only for the session pending lock

New persistent HTTP-bridge sessions construct `pending_lock` as `anyio.Lock(fast_acquire=True)`. The lifecycle and prewarm locks retain their default checkpoint behavior because they are not acquired per upstream frame and coordinate broader session transitions.

Keeping AnyIO avoids a nominal type and cancellation-semantics cutover. AnyIO fast acquisition still respects already queued waiters; it only removes the forced yield when the lock is free and no waiter exists.

Alternative: use `asyncio.Lock`. Rejected because the measured fast path is materially equivalent while the API and backend assumptions change. Alternative: enable fast acquisition for every session lock. Rejected because there is no measured benefit for lifecycle or prewarm operations.

### Checkpoint only after a fully handled frame

The upstream reader counts completed text frames. It initializes the counter so the first frame triggers a checkpoint, then checkpoints once every 32 completed frames. A frame is complete only after `_process_http_bridge_upstream_text` has parsed it, selected and mutated pending ownership under the lock, archived it, queued or suppressed its downstream event, emitted a terminal sentinel when applicable, finalized settlement, and completed the retirement check.

The checkpoint therefore occurs before the next `upstream.receive()`, never between receive and attribution. A request enqueued during the checkpoint cannot claim the frame that caused the checkpoint, but it can be available for later upstream responses. The first checkpoint lets a task that became ready during the first receive run before a fully prebuffered burst drains; subsequent checkpoints bound starvation to 31 additional text frames.

Alternative: rely on upstream receive or queue puts to yield. Rejected because both can complete synchronously for buffered I/O and unbounded queues. Alternative: checkpoint immediately after receive. Rejected because it breaks causal archive and response attribution.

### Make contention and starvation part of the correctness digest

The HTTP-bridge benchmark adds two independent cases. The contention case overlaps request enqueue with the real reader, cancels a waiter queued behind a held pending lock, then verifies response routing, archive request ids, terminal sentinels, pending cleanup, and queued-count restoration. The ready-enqueue case wakes a marker from the first upstream receive and requires it to acquire the pending lock before the prebuffered burst has fully drained.

These cases run before timing. Their results join the fixed correctness digest, so changing lock cancellation, scheduler fairness, frame order, archive ownership, or cleanup requires an explicit contract update rather than appearing as a speedup.

## Risks / Trade-offs

- A fast lock could starve a task that is ready but not yet queued as a waiter -> checkpoint after the first completed frame and every 32 completed frames; assert ready-enqueue progress before full drain.
- A checkpoint could let a later request claim an already received frame -> place the checkpoint only after archive, matching, downstream queueing, finalization, and retirement handling for that frame.
- A cancelled waiter could disturb AnyIO's owner handoff -> cancel a real contended waiter in the benchmark and assert the relay proceeds with exact ownership and cleanup.
- A synthetic benchmark may overstate end-to-end gains -> report relay CPU/scheduler cost only and preserve route-level integration tests for behavior.

## Migration Plan

1. Extend and lock the benchmark correctness digest while the production lock remains on its default policy.
2. Enable fast acquisition and the completed-frame checkpoint together.
3. Run the benchmark, full HTTP-bridge unit and integration suites, lint, type checks, and strict OpenSpec validation.
4. Roll back both the fast-acquire flag and checkpoint as one change if scheduling or ownership regressions appear; no data migration or persisted-state repair is required.

## Measured Results

The benchmark was run three independent times before and after the lock-policy change. Each invocation used 3 warmups and 21 measured samples over the same 536-event workload. The expanded correctness digest remained `97b1314a65c626f83e76337f9489ee9a373dd5c3b411122b61335ae8b71ffa5b` in every run.

| Case | Default-lock median ns/event | Bounded fast-lock median ns/event | Median improvement | Default-lock p95 ns/event | Bounded fast-lock p95 ns/event | p95 improvement |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Concurrent consumers | 60,975.203 | 18,593.983 | 69.51% | 65,674.830 | 19,558.614 | 70.22% |
| Backlogged consumers | 55,057.759 | 18,335.043 | 66.70% | 62,523.709 | 18,990.750 | 69.63% |

The median aggregate score increased from 1,067.596265 to 3,358.334978 (+214.57%). These measurements isolate relay CPU and scheduler cost; they do not claim equivalent end-to-end network latency gains.

## Open Questions

None.
