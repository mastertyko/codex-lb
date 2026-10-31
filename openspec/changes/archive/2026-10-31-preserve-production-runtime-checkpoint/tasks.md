## 1. Capture and provenance

- [x] 1.1 Record the live image, source manifest, dependency versions and native binary hash without mutating production.
- [x] 1.2 Assemble exact application/script/registry source and matching frontend inputs in an isolated checkpoint branch.
- [x] 1.3 Record portable provenance and a verifier without credentials, account records or host-specific paths.

## 2. Verification

- [x] 2.1 Verify exact source parity and a byte-identical frontend rebuild.
- [x] 2.2 Verify the captured migration graph and isolated migration upgrade/check behavior.
- [x] 2.3 Run relevant tests and the repository's local gate; record passing checks and any preserved baseline limitations separately.
- [x] 2.4 Validate OpenSpec strictly and verify that production and existing worktrees remain unchanged.

## 3. Delivery

- [x] 3.1 Commit the reviewed checkpoint and push only its explicit topic ref to the fork.
- [x] 3.2 Verify local and fork commit equality and record the final validation evidence.
