## 1. Progress tracking

- [x] 1.1 Record the monotonic time of each matched upstream HTTP bridge event on its request state.
- [x] 1.2 Use last upstream progress, falling back to request start, when classifying a pre-response-created gate holder as stale.

## 2. Regression coverage

- [x] 2.1 Verify silent holders and holders with one old upstream event are retired after inactivity.
- [x] 2.2 Verify a holder with recent upstream progress is not retired despite old total age.
- [x] 2.3 Verify late cleanup of a retired bridge cannot release a replacement bridge gate.

## 3. Validation

- [x] 3.1 Run focused HTTP bridge unit tests and changed-file diagnostics.
- [x] 3.2 Run strict OpenSpec validation for the completed change.
