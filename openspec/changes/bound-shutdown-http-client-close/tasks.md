## 1. Regression coverage

- [x] 1.1 Prove a managed client that never reports itself closed no longer
  pins shutdown, and that its close is abandoned rather than cancelled.
- [x] 1.2 Prove a prompt close is still awaited normally.
- [x] 1.3 Prove a raising close does not fail shutdown.

## 2. Bounded close

- [x] 2.1 Run the managed HTTP client close as a task and wait for it under the
  same 10s budget the leader lease release uses.
- [x] 2.2 Abandon the wait on deadline and log the eventual outcome from a done
  callback.

## 3. Verification

- [x] 3.1 Run the graceful-shutdown unit suite.
- [x] 3.2 Run lint, formatting, type checks, and the proxy architecture check.
- [x] 3.3 Run strict OpenSpec validation for this change.
