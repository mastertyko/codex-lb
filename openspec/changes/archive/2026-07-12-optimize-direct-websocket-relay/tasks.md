## 1. Archive Attribution Correctness

- [x] 1.1 Keep malformed `response.created` frames without response ids unattributed.
- [x] 1.2 Add regression coverage for malformed and multiplexed archive ownership.

## 2. Direct WebSocket Relay Optimization

- [x] 2.1 Share one parsed-frame value between archive matching and downstream processing, with typed models limited to terminal events.
- [x] 2.2 Remove the redundant archive snapshot lock while preserving the event-loop-local no-await invariant.
- [x] 2.3 Enable fast uncontended session locks and add a bounded relay scheduling checkpoint.

## 3. Deterministic Measurement

- [x] 3.1 Add a real direct-WebSocket relay benchmark with fixed byte, order, ownership, terminal-cleanup, contention, cancellation, and fairness contracts.
- [x] 3.2 Record the baseline, profile confirmed bottlenecks, and verify the post-change per-event improvement.

## 4. Verification

- [x] 4.1 Run the full direct-WebSocket integration and proxy utility suites.
- [x] 4.2 Run changed-file lint, type checks, and language-server diagnostics.
- [x] 4.3 Run strict OpenSpec validation for the completed change.
