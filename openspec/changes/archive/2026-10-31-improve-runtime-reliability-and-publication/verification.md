# Verification

All targets in the repository's local `make ci` chain were exercised. The long Python selections ran as the existing three verified integration-core shards and focused reruns after fixes, rather than one uninterrupted invocation. Raw logs, synthetic databases, browser screenshots and temporary Git repositories remain outside the source tree.

| Area | Evidence |
| --- | --- |
| Publication privacy | Real Gitleaks scanning of the intended tree: 5,992 files, zero unreviewed findings before documentation finalization. CLI regressions cover removed-in-a-later-commit secrets, metadata, missing tooling, exact exceptions, redaction and repository scanner-config bypasses. |
| Build provenance | Dirty-source rejection tests and real Docker build from an isolated clean verification commit. Image revision, frozen inputs and platform match the portable receipt. This private fixture is not a published release. |
| Python units and simulation | Full selection: 10,769 passed, 7 skipped, 1 expected failure. New owner-proof tests and affected file-client/tooling paths also pass separately. |
| Integration core | All three existing shards completed; each discovered failure was resolved and the affected files or regression slices rerun. The restored native owner tests pass through real routing and alternate-account rejection. |
| HTTP bridge | Full file: 196 passed. |
| WebSocket and file routing | Full WebSocket file plus file routing, reconnect, paused-account and cache-invalidation coverage: 243 passed. |
| End to end | 29 passed, 1 skipped. |
| PostgreSQL and migrations | Configured PostgreSQL suite: 256 passed. SQLite and PostgreSQL migration checks passed. Restored migration benchmark: 12 passed against disposable PostgreSQL. |
| Frontend | Lint, typecheck and build passed; 181 test files / 1,713 tests passed. Real browser request-details checks passed at desktop and mobile sizes. |
| Rust | Formatting, clippy, release build, 28 tests and dependency policy/audit passed. |
| Python static gates | Lint, typecheck, architecture, cancellation safety, timing seams, settings tiers and single-head migration topology passed. |
| Packaging | Source distribution and wheel built; dashboard assets verified in the wheel. Development dependencies restored afterward. |
| Container and Helm | Final image passed the CRITICAL vulnerability gate and isolated liveness/readiness/dashboard/schema checks. Helm lint, templates, kubeconform and both bundled/external-database kind smoke variants passed. |
| Specifications | All 19 delta requirements match canonical specifications; strict change and canonical validation passed. |

## Correctness and boundaries

- Probe payload and conservative capacity handling are covered by account/dashboard regressions. SQLite historical fetches retain the recent floor while bounding the older tail, with PostgreSQL parity coverage.
- Pricing basis is captured with the original effective rates and model-rate fingerprint. Catalog-drift, service-tier/context multipliers, provider totals, legacy rows and migration recovery have regression coverage.
- Shared quota helpers no longer depend on a sibling transport implementation. Production lifecycle code uses owned clock/scheduler seams; architecture and cancellation thresholds were not relaxed.
- The inherited routed-file fix preserves typed replay eligibility through both wrappers and prohibits account switching after any finalize poll returned a response.
- Native owner-bound full resends keep complete history on the recorded account. Unavailable owners cannot authorize relocation using only a same-owner proof.
- Transport tests record the observed HTTP/WebSocket transport independently of the requested `auto` policy. Mock-account fixtures are separate from real database-backed pause/delete coverage.
- Publication still requires the documented checked-push wrapper. CI is an additional check after upload; it does not replace the local gate. Pattern scanning and narrow reviewed exceptions do not remove the need for a human review of newly included content.
- Implementation verification completed before publication and without a production cutover. Subsequent authorized publication and deployment are recorded separately. The original checkpoint branch remains unchanged. Private verification commits are disposable test artifacts only.
- An upstream PR carrying the existing settings-budget reconciliation still needs the maintainer's `simplicity-budget-approved` label. Local checks do not imply GitHub CI, review or merge approval.
