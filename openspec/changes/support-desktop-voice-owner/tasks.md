## 1. Baseline and contracts

- [x] 1.1 Extract only Desktop Voice changes onto current public upstream main; exclude private runtime history and unrelated changes.
- [x] 1.2 Preserve exact identity, registered-key admission, key scope, pause, privacy and rollback contracts.

## 2. Authentication and Voice implementation

- [x] 2.1 Separate gateway and caller credentials for supported HTTP and WebSocket routes; retain legacy key authentication and pooled credential isolation.
- [x] 2.2 Verify callers at a fixed trusted native origin before exact stored user/workspace lookup and fresh owner checks.
- [x] 2.3 Implement explicit native sideband and app-server creation with bounded cleanup, exact-owner capacity and unchanged pause status.
- [x] 2.4 Accept the bounded native attestation envelope without weakening malformed-input or authorization checks.
- [x] 2.5 Add fixed rejection diagnostics that preserve public responses and exclude request data.
- [x] 2.6 Reuse shared Live transport/header support while preserving facade exports, architecture budgets and per-rule timing allowance totals; full architecture checks pass.

## 3. Public candidate verification and delivery

- [x] 3.1 Run focused regressions against the public candidate: initial route/credential/privacy selection 534 passed; after shared-support extraction, Desktop/legacy realtime/header/architecture selection 591 passed. Scoped Ruff, type checks and diff checks passed.
- [x] 3.2 Document the actual Desktop model, microphone, transcript, delegation and audible-output proof, with direct call/media versus LB sideband boundaries.
- [x] 3.3 Sync requirements and stable context, and document reversible client configuration.
- [x] 3.4 Validate the change and main specs strictly: scoped change and affected specs pass; all 17 global failures match upstream main exactly (candidate 51 pass/17 fail, base 50 pass/17 fail).
- [x] 3.5 Run the repository's full mandatory local-ci gate in isolated resources. Final attempt passed frontend (1649 tests), architecture, Ruff, ty and Rust; unit tests reported 10596 passed, 7 skipped and one failure reproduced identically in upstream on macOS. Full CI remains FAILED; later integration/e2e/PostgreSQL/migration/package/Docker/Helm stages did not complete. Additional broad integration checks were stopped for this fork checkpoint; no full-CI-green claim is made.
- [x] 3.6 Independently review the committed publication diff and structural delta; resolve the documentation-link finding. No remaining actionable findings or private material were identified.
- [x] 3.7 Scan unpublished history and preserve only scoped code, tests and public documentation for topic-branch publication.
- [ ] 3.8 Archive after the remaining repository-wide verification can complete. This fork checkpoint retains the active change and its explicit verification limits.
