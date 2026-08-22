## 1. Regression coverage

- [x] 1.1 Prove a remote transport peer cannot start drain or commit the
  shutdown barrier by projecting a loopback forwarded client.
- [x] 1.2 Prove the same peer cannot stop drain or read drain status.
- [x] 1.3 Prove a loopback transport peer stays authorized while forwarding
  projection names a remote client.
- [x] 1.4 Prove a request without preserved raw-peer provenance is rejected.

## 2. Raw-peer authorization

- [x] 2.1 Resolve the drain guard from the launcher-preserved raw socket peer.
- [x] 2.2 Fail closed when raw-peer capture is unavailable.
- [x] 2.3 Collapse the three duplicated inline guards into one helper.

## 3. Verification

- [x] 3.1 Run the new drain access tests plus the existing graceful-shutdown
  and health probe suites.
- [x] 3.2 Run lint, formatting, type checks, and the proxy architecture check.
- [x] 3.3 Run strict OpenSpec validation for this change.
