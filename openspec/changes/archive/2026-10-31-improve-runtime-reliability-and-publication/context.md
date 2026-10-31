# Verification decisions

The preserved runtime already contains `desktop_oauth_grants`, a T1 deployment trust boundary that binds explicitly admitted native callers to existing local policy keys. Its empty default admits nobody. Inferring this mapping from a valid upstream login would grant local access without the operator's authorization, so a universal inferred default is unsafe. Removing the field to satisfy the configuration count would remove an existing security control.

The change therefore includes a reviewable settings-budget adjustment from 96 to 97, plus regeneration of the settings reference, to account for exactly that existing field. It adds no configuration option. An upstream PR carrying this exception still needs the maintainer's `simplicity-budget-approved` label and this why-not-a-default rationale in its body under the configuration-tiers specification. Local validation does not assert upstream approval or PR readiness. Proxy architecture, timing and cancellation limits remain unchanged.

The native dependency audit also identified advisories in the checkpoint's locked Rust dependencies. The affected TLS, async-runtime and decompression packages are upgraded to patched compatible releases, preserving the HTTP/WebSocket feature set. Rust tests, audit and the native integration paths must pass against the new lockfile before verification is complete.

The original checkpoint branch and its source/build manifest remain unchanged. Test databases, build receipts, browser artifacts and raw verification logs stay outside the source tree; no production cutover is part of this work.

## Reconcile inherited upstream fixes

The runtime snapshot retained source overrides that preceded four upstream fixes, while their regression tests were already present. Restore single control-request Content-Type fields, spendable-credit quota checks, typed unary failover provenance, and retryable WebSocket drain denials. Preserve the separate native terminal behavior and its matching tests. These changes are verified locally before any publication or deployment.

The container gate also reported GHSA-6q48-6c7w-9gw2 in the inherited certifi bundle. The frozen Python lock is updated from 2026.7.22 to 2026.10.23, which removes the affected trust root. The rebuilt image must pass the existing CRITICAL vulnerability gate. Advisory: https://github.com/advisories/GHSA-6q48-6c7w-9gw2.

The checkpoint retained migration-benchmark integration tests from upstream commit cd9b4084a but omitted their two command modules and owning specification. Restore those exact upstream modules and requirements so the existing disposable-database tests verify the intended tool. No benchmark runs against production.

Restore native owner-bound resend regression tests and their normative requirement from b754e64e6. The same-owner proof deliberately keeps complete tool history unanchored even when the stricter account-neutral proof rejects it. The older Lite integration test now verifies the preserved body and disabled owner fallback; alternate-owner rejection remains covered through the real selector.

The restored owner-bound replay tests exposed omitted safety checks in the snapshot: malformed metadata and unknown preamble fields were accepted, and the unavailable-owner retirement path could relocate history that only had a same-owner proof. Reinstate the validated checks from b754e64e6 and verify unavailable-owner behavior through the real selector.


The routed-file reconciliation includes both the low-level error wrapper and the service translation: typed replay eligibility must survive both boundaries, including the prohibition on switching accounts after a finalize poll returned a response.

Transport integration fixtures now supply observed HTTP/WebSocket evidence instead of asserting the requested `auto` policy as an actual transport. The mock WebSocket account fixtures use a local availability view because they deliberately bypass account persistence; real paused/deleted-account and cache-invalidation route tests still use the database-backed cache. Quarantine tests establish the failed proxy-injected anchor with a delta continuation, since the owner-proof behavior correctly preserves complete resends without adding an anchor. Source cancellation is injected after reservation ownership is established rather than in the earlier pre-reservation payload-shaping step.
