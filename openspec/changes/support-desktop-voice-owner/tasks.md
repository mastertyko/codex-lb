## 1. Baseline and contracts

- [x] 1.1 Extract only Desktop Voice changes onto current public upstream main; exclude private runtime history and unrelated changes.
- [x] 1.2 Preserve exact identity, registered-key admission, key scope, pause, privacy and rollback contracts.

## 2. Authentication and Voice implementation

- [x] 2.1 Separate gateway and caller credentials for supported HTTP and WebSocket routes; retain legacy key authentication and pooled credential isolation.
- [x] 2.2 Verify callers at a fixed trusted native origin before exact stored user/workspace lookup and fresh owner checks.
- [x] 2.3 Implement explicit native sideband and app-server creation with bounded cleanup, exact-owner capacity and unchanged pause status.
- [x] 2.4 Accept the bounded native attestation envelope without weakening malformed-input or authorization checks.
- [x] 2.5 Add fixed rejection diagnostics that preserve public responses and exclude request data.

## 3. Public candidate verification and delivery

- [x] 3.1 Run focused route, owner, credential, client, header and privacy regressions against the public candidate: 534 passed; scoped Ruff, type checks and diff checks passed.
- [x] 3.2 Document the actual Desktop model, microphone, transcript, delegation and audible-output proof, with direct call/media versus LB sideband boundaries.
- [x] 3.3 Sync requirements and stable context, and document reversible client configuration.
- [ ] 3.4 Validate the change and main specs strictly, reporting any unchanged baseline failures separately.
- [ ] 3.5 Run the repository's full mandatory local-ci gate against the exact publication candidate in isolated resources.
- [ ] 3.6 Independently review the committed publication diff and fix actionable findings.
- [ ] 3.7 Archive only the verified change and scan unpublished history for private material before topic-branch publication.
