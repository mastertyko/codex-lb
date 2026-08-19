## 1. Specification

- [x] 1.1 Define missing-field stale-anchor classification and client recovery.
- [x] 1.2 Define retry-safety versus cross-account portability invariants.

## 2. Implementation

- [x] 2.1 Add failing regressions for code-less stale-anchor envelopes.
- [x] 2.2 Emit canonical recovery for client-owned delta-only continuations.
- [x] 2.3 Gate account-changing replay on canonical account-neutral proof.
- [x] 2.4 Keep account-bound stale replays pinned after anchor removal.
- [x] 2.5 Gate HTTP-to-WebSocket fallback on the same portability proof.

## 3. Verification

- [x] 3.1 Run focused classifier, WebSocket, bridge, and replay-safety tests.
- [x] 3.2 Run full lint, type, backend, and strict OpenSpec gates.
- [x] 3.3 Exercise repeated foreground and background continuations through deployment.
- [x] 3.4 Obtain an independent security review of account movement.
