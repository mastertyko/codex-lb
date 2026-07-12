## 1. Restore HTTP Bridge Runtime

- [x] 1.1 Restore the default pending lock, `asyncio.wait_for` receive and queue waits, eager event parsing and response/error derivation, awaited queue puts, and the beta.3 HTTP relay scheduling path with no explicit frame-count checkpoint.
- [x] 1.2 Remove the now-unused `parse_event=False` tool-call rewrite API and its optimization-only test while preserving unrelated relay behavior.

## 2. Add Failure-Only Close Attribution

- [x] 2.1 Define and thread a finite HTTP bridge close-reason type through every production close callsite, distinguishing idle pruning from generic registry detachment.
- [x] 2.2 Persist close reason and actual per-request draining state through existing failure metadata without suppressing `stream_incomplete` or overwriting more specific diagnostics.
- [x] 2.3 Add observable regression coverage for idle-prune closure of a draining request and registry-detach closure of a non-draining request.

## 3. Align Deterministic Measurement and Existing Tests

- [x] 3.1 Update existing HTTP bridge tests to the restored lock and scheduling contracts while retaining attribution, order, cancellation, contention, timeout, sentinel, and cleanup coverage.
- [x] 3.2 Keep the HTTP bridge benchmark on beta.3 production scheduling, retain its routing, ownership, archive, order, cancellation, contention, timeout, sentinel, cleanup, and timing coverage, and remove any requirement for a ready enqueue to run before a finite prebuffered burst drains.

## 4. Verify the Release Candidate

- [x] 4.1 Run all touched focused suites and all four deterministic benchmarks on the exact final SHA, confirming every locked correctness digest and reporting metrics.
- [x] 4.2 Run one finite-timeout full pytest on the exact final SHA, Ruff format-check/lint, ty, changed-file LSP diagnostics, strict change and main-spec validation, migration upgrade/check, and `git diff --check`.
- [x] 4.3 Verify exact-final-SHA implementation completeness, correctness, design coherence, upstream-release preservation, and residual risks; keep the change active and local for future external audit.

## 5. Correct Reservation and Account-Health Ordering

- [x] 5.1 Atomically take and clear every remaining request reservation under pending-lock ownership, then cancel heartbeats and settle all taken reservations before any account-health mutation without holding the lock across awaits.
- [x] 5.2 Exclude draining states from health-penalty selection while preserving at most one existing non-draining penalty and full failure, sentinel, terminal, gate, and request-log finalization for every state.
- [x] 5.3 Add production-shaped draining-only, mixed-state ordering, and non-draining ordering regressions with explicit reservation and account-health spies.
- [x] 5.4 Run focused bridge, proxy-utils, and API-key tests; Ruff format/lint; ty; changed-file LSP diagnostics; strict OpenSpec validation and verification; and `git diff --check`.

## 6. Preserve Finalization Across Reservation Release Errors

- [x] 6.1 Retain request-reservation ownership pairs, isolate every non-null initial release attempt, and transfer each failed ownership exactly once to fresh cancel-safe background cleanup with finite opaque attribution.
- [x] 6.2 Suppress account-health mutation for an unsettled batch while preserving non-draining-only selection after all-success settlement and all-state gate, failure, sentinel, terminal, and request-log finalization in both outcomes.
- [x] 6.3 Add a deterministic two-state partial-release regression proving later release, background transfer, zero health mutation, no duplicate initial release, and complete finalization while retaining the existing success and detach-race coverage.
- [x] 6.4 Run focused pending-failure, HTTP bridge, API-key usage, and cancel/drain tests; Ruff format/lint; ty; changed-file LSP diagnostics; strict OpenSpec validation and verification; and `git diff --check`.

## 7. Bound Partial-Release Background Cleanup

- [x] 7.1 Collect failed reservation ownership as opaque identifier/reservation pairs and schedule at most one cancel-safe batch retry that attempts each failed reservation sequentially exactly once with per-item error isolation and no nested task fan-out.
- [x] 7.2 Strengthen the partial-release regression with simultaneous initial and retry failures, proving one scheduled cleanup, ordered one-shot retries, later-retry progress, suppressed health mutation, and complete foreground finalization while retaining existing success and detach-race coverage.
- [x] 7.3 Run the focused pending-failure, HTTP bridge, API-key usage, and cancel/drain suites; Ruff format/lint; ty; changed-file LSP diagnostics; strict OpenSpec validation and verification; and `git diff --check`.

## 8. Own Shared Batch Retries Through Shutdown

- [x] 8.1 Make the settlement and bounded-retry contract explicitly shared by HTTP-bridge and direct-WebSocket pending cleanup while keeping close-reason attribution HTTP-specific, and include the transport-neutral batch-retry task class in the existing bounded shutdown drain.
- [x] 8.2 Add a direct/generic pending-cleanup regression with a blocked batch retry spanning `close_all_http_bridge_sessions`, proving shutdown waits, completion removes ownership cleanly, and one-task sequential retry behavior remains intact.
- [x] 8.3 Run focused proxy-utils, HTTP bridge, shutdown, API-key usage, and cancel/drain tests; Ruff format/lint; ty; changed-file LSP diagnostics; strict OpenSpec validation and verification; and `git diff --check`.

## 9. Cancel Timed-Out Shared Batch Retries

- [x] 9.1 Distinguish finite shared reservation batch-retry tasks in the bounded shutdown drain and, on timeout, explicitly cancel and await their terminal cleanup with the existing cancellation helper while preserving timeout behavior for other task classes.
- [x] 9.2 Add a true timeout-path regression that never releases the blocked retry, uses a short drain timeout, and proves cancellation is delivered and awaited, task ownership is removed, and shutdown returns only afterward; retain the normal blocked-then-released regression.
- [x] 9.3 Run focused proxy-utils, HTTP bridge, shutdown, API-key usage, and cancel/drain tests; Ruff format/lint; ty; changed-file LSP diagnostics; strict OpenSpec validation and verification; and `git diff --check`.

## 10. Preserve Post-Take Cleanup Across Cancellation

- [x] 10.1 Refactor cancel-safe cleanup ownership so it can adopt one already-created task, make coroutine scheduling delegate to that tracker, and run the entire post-reservation-take release, retry-transfer, health, and finalization phase in exactly one finite-prefix owned child awaited through shield.
- [x] 10.2 Extend shutdown draining to the post-take task class, rescan relevant owned task classes to quiescence within one deadline, retain explicit cancel-and-await for timed-out reservation retries, and implement a bounded cancellation-safe timed-out post-take policy that leaves no repository task alive at database teardown.
- [x] 10.3 Add deterministic direct-WebSocket reader-owner cancellation, shutdown quiescence-rescan, and timed-out post-take regressions while retaining normal and timed-out reservation-retry drain coverage.
- [x] 10.4 Run focused WebSocket, proxy-utils, HTTP bridge, shutdown, API-key usage, and cancel/drain suites; Ruff format/lint; ty; changed-file LSP diagnostics; strict OpenSpec validation and verification; and `git diff --check`, while leaving release tasks 4.1–4.3 open.

## 11. Await Each Finalizer Operation Exactly Once

- [x] 11.1 Broaden proposal impact and design scope to cover shared HTTP/direct-WebSocket settlement ordering, draining health neutrality, partial-release batch retry, foreground post-take ownership, single-invocation finalizers, and shutdown cancellation/quiescence.
- [x] 11.2 Refactor the cancellation-preserving finalizer await so each operation is created once as a local task under the single tracked post-take child and only that same shielded task is re-awaited to terminal completion, with no nested task wrapping, duplicate side effects, or live request-log persistence transfer.
- [x] 11.3 Add deterministic blocked terminal-send, blocked log-finalizer, and real blocked `_persist_request_log` shutdown regressions proving exactly-once effects and quiescence of both cleanup registries, while retaining all owner-transfer, rescan, retry-timeout, settlement, and finalization coverage.
- [x] 11.4 Run focused proxy-utils, request-log, shutdown, HTTP bridge, API-key usage, and WebSocket suites; Ruff format/lint; ty; changed-file LSP diagnostics; strict OpenSpec validation and semantic verification; and `git diff --check`, while leaving release tasks 4.1–4.3 open.

## 12. Keep Finalizer Ownership Local to One Tracked Child

- [x] 12.1 Remove independent finalizer action, prefix, tracker registration, and shutdown-drain classes while preserving one local exactly-once operation task that the sole tracked post-take parent cannot outlive.
- [x] 12.2 Update blocked send, blocked log, and real request-log persistence regressions to prove the background registry contains only the post-take parent unless a reservation batch retry is independently required, with both cleanup registries empty at shutdown return.
- [x] 12.3 Run the same focused proxy-utils, request-log, shutdown, HTTP bridge, API-key usage, and WebSocket suites; Ruff format/lint; ty; changed-file LSP diagnostics; strict OpenSpec semantic validation; and `git diff --check`, while leaving release tasks 4.1–4.3 open.

## 13. Commit Unusable-Upstream State Before Terminal Events

- [x] 13.1 Audit every upstream-reader pending-failure callsite and move reconnect or retirement assignment before client-visible terminal publication only where the upstream socket is unusable, preserving downstream-disconnect, per-request expiry, transparent replay, and intentionally reusable-socket paths.
- [x] 13.2 Run the stalled-upstream integration regression with a finite command timeout and adjacent direct-WebSocket and cleanup suites, adding a narrow order assertion only if the existing integration contract does not prove immediate follow-up routing.
- [x] 13.3 Run Ruff format/lint, ty, changed-file LSP diagnostics, strict OpenSpec validation and semantic verification, and `git diff --check`, while leaving release tasks 4.1–4.3 open.

## 14. Rebase Semantically onto Verified Beta.3

- [x] 14.1 Verify the beta.3 annotated tag target and GitHub-signed commit, read official release notes and PRs #1191, #1169, #1220, #1219, #1207, and #1223, and classify overlapping local work before editing.
- [x] 14.2 Reapply the non-overlapping core/SSE/balancer/chat and SQLite usage hot paths with their hot-path and dashboard-query benchmark entrypoints and focused regressions.
- [x] 14.3 Port the direct-WebSocket parse-once and bounded-fairness optimization into the beta.3 reader without weakening reconnect affinity, incomplete reasons, safe owner replay, or sequenced-replay refusal; retain the deterministic WebSocket benchmark.
- [x] 14.4 Retain beta.3 HTTP scheduling, add finite close attribution, and port reservation-before-health, draining and unsettled neutrality, bounded batch retry, one tracked post-take child, exactly-once local finalizers, shutdown quiescence, and unusable-upstream state-before-terminal ordering.
- [x] 14.5 Reconcile delta and main specs, preserve beta.3 migrations and release metadata, and pass the immediate-follow-up regression plus adjacent upstream close/replay/incomplete/cancellation and touched focused suites before final gates.

## 15. Preserve Current-Main Product Contracts

- [x] 15.1 Inventory every current-local-`main` commit absent from the beta.3 candidate and classify each delta as upstreamed, semantically ported, intentionally superseded, or missing before history reconciliation.
- [x] 15.2 Restore the privacy-safe `GET /api/activity/state` module, router registration, host-poller contract, main specification/context, and focused API/service regressions without changing persistence schemas.
- [x] 15.3 Port stale-anchor source, replay, owner-lookup, age, same-session, and explicit-unknown diagnostics onto the beta.3 replay, incomplete-reason, reconnect-affinity, and sequenced-replay structures; restore request-log and direct-WebSocket regressions.
- [x] 15.4 Reconcile the active delta specifications, design/context rationale, and main specifications, then rerun focused activity, stale-anchor, WebSocket, and HTTP-bridge suites plus final static, OpenSpec, migration, diff, and finite-timeout full-suite gates on the completed candidate.
- [x] 15.5 Verify final implementation completeness, correctness, and design coherence; record the exact pre-merge candidate tree; reconcile histories with current `main` as a merge parent while preserving that tree; fast-forward local `main`; and prove post-merge tree identity, clean refs/worktree, and focused smoke behavior.
