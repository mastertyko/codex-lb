## 1. Correctness Baseline

- [x] 1.1 Extend the HTTP-bridge relay benchmark with concurrent enqueue and exact archive/frame-order coverage.
- [x] 1.2 Add pending-lock waiter cancellation and ready-enqueue starvation contracts to the correctness digest.
- [x] 1.3 Lock the expanded correctness digest and default-lock performance baseline.

## 2. Relay Lock Optimization

- [x] 2.1 Enable fast acquisition only for newly created persistent HTTP-bridge pending locks.
- [x] 2.2 Add a bounded scheduler checkpoint after a fully processed text frame and before the next receive.

## 3. Verification

- [x] 3.1 Verify the benchmark digest remains stable and record the post-change median and p95 improvement.
- [x] 3.2 Run focused and full HTTP-bridge unit and integration suites.
- [x] 3.3 Run changed-file lint, type checks, diagnostics, and strict OpenSpec validation.
