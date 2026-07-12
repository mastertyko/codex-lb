# HTTP Bridge Fast-Path Rollback Context

## Purpose and Scope

This change prepares a conservative measurable-performance candidate on verified upstream release commit `a225f0db0c3e00224d3f4256590d5d05dfa763d4` (`v1.21.0-beta.3`). It retains the release's overlapping HTTP bridge and direct-WebSocket fixes, preserves the release's already-restored HTTP runtime semantics, reapplies only non-duplicated measured optimizations, and adds failure-only attribution plus shared cleanup guarantees. Normative behavior is defined in the delta `spec.md` files; this document records rationale, overlap evidence, and operational context.

Before history reconciliation, this change also restores every non-superseded product contract found only on local `main`: the privacy-safe activity endpoint, stale-anchor diagnostic metadata with explicit unknowns, query-performance requirements already implemented by the candidate, and malformed direct-WebSocket archive attribution. These are preservation deltas relative to beta.3, not scope expansion relative to the product currently exposed by local `main`.

## Observed Evidence

The canary recorded four HTTP-to-WebSocket `stream_incomplete` rows among 82 requests. One was an upstream abnormal close at approximately 13.3 seconds. Three were local bridge session closes at approximately 123 seconds, close to the configured 120-second idle TTL. All four belonged to one sanitized cohort that was absent from both comparison windows. Prior `8c17e62c` traffic recorded one incomplete row among 318 requests; an equal restored window recorded zero among 22.

A deterministic detach/prune/close harness reproduced the local bridge-close record with both AnyIO's default pending lock and `fast_acquire=True`. The harness proved a plausible misattribution path but did not prove that the optimized runtime caused the live failures or that the live requests followed that path.

## Upstream Beta.3 Overlap Evidence

The fetched annotated tag resolves locally to `a225f0db0c3e00224d3f4256590d5d05dfa763d4`; GitHub marks that commit's PGP verification as valid. The tag object itself is unsigned, so commit verification and the official release target are the trust evidence. Official beta.3 notes include HTTP admission-waiter recovery (#1191), unanchored bridge isolation (#1169), WebSocket reconnect affinity (#1220), incomplete-reason fidelity (#1219), safe turn reselection and owner replay (#1207), and sequenced-replay refusal (#1223).

Those upstream implementations supersede the older local sequence/replay and broad source shapes and must remain authoritative. The local core parser, SSE, balancer, chat-mapping, usage-query, and deterministic benchmark paths have no upstream changes after the shared base and remain non-duplicated. The local `f787f10c` HTTP fast path is not present in beta.3, so the rollback is satisfied by retaining beta.3's current HTTP scheduling implementation rather than copying older bridge files. Finite close attribution and the shared reservation/health/finalization/shutdown contract remain absent and are reapplied semantically on top.

## Current-Main Semantic Inventory

The pre-merge inventory compared every commit reachable from local `main` (`efa4b4fa`) but not from the original candidate (`c0680fc3`) before any history reconciliation. Classification is semantic: upstream beta.3 structures remain authoritative when they supersede older local source shapes, while observable local contracts remain mandatory.

| Local-main commit | Classification | Candidate disposition |
|---|---|---|
| `03c5482` activity state endpoint | Missing, now semantically ported | Restore the module, dependency/provider, router registration, repository aggregate, host-poller API contract, main/active specs, and focused tests without copying the archived change directory. |
| `cb74c0c` sequenced WebSocket replay refusal | Upstreamed | Beta.3 contains upstream #1223 (`4f891a6a`) with its source, OpenSpec delta, and regression coverage; retain that implementation unchanged. |
| `830e978` stale-anchor diagnostics | Missing, now semantically ported | Layer failure-only metadata onto beta.3's #1207/#1219/#1220/#1223 owner, replay, incomplete, and reconnect structures; do not restore the older resolver wholesale. |
| `af888a04` stale-diagnostic expectation repair | Missing supporting coverage, now semantically ported | Restore equivalent sanitizer, transport, owner-source, and request-log assertions against the beta.3-shaped implementation. |
| `372bda56` autoresearch harness setup | Already semantically ported | Candidate `a7b8c761` carries the final harness and production-default benchmark entrypoints; targeted script blobs match local `main`. |
| `a167e0bf` SSE iterator fast path | Already semantically ported | Candidate `a7b8c761` carries the final implementation; the source blob matches local `main`. |
| `c89a395c` first usage-query optimization | Intentionally superseded by its later local refinement | The final batching/query shape from `d0b7e9d4`, not this intermediate shape, is carried by candidate `30753eef`. |
| `00517dfc` request-body parse reduction | Already semantically ported | Candidate `a7b8c761` carries the final source blob from local `main`. |
| `65fb7f25` rendezvous byte cache | Already semantically ported | Candidate `a7b8c761` carries the final source blob from local `main`. |
| `55e35a8a` balancer copy reduction | Already semantically ported | Candidate `a7b8c761` carries the final source blob from local `main`. |
| `f4e1dd1c` account-status reconciliation batching | Already semantically ported | Candidate `a7b8c761` carries the final source blob from local `main`. |
| `e6fe495d` chat-request mapping optimization | Already semantically ported | Candidate `a7b8c761` carries the final source blob from local `main`. |
| `2e7b5472` request-log report batching | Already semantically ported | Candidate `a7b8c761` carries the final source blob from local `main`. |
| `41523e6e` follow-up batch correctness/finalization | Already semantically ported | Candidate `a7b8c761` carries the corrected final source and coverage rather than the earlier intermediate state. |
| `d0b7e9d4` additional-usage batching | Already semantically ported | Candidate `30753eef` carries the final repository source blob from local `main`. |
| `abfcb1a2` production-default lock benchmark | Already semantically ported | Candidate `30753eef` carries the benchmark contract; later candidate benchmark commits rebaseline only the intentionally restored HTTP runtime. |
| `f787f10c` HTTP bridge relay fast path | Intentionally superseded for product runtime; measurement preserved | Exclude its custom lock, timeout, parse, queue, and checkpoint bundle because beta.3's conservative scheduler is the release baseline; retain and rebaseline the deterministic HTTP benchmark against production defaults. |
| `6ce9ac21` direct-WebSocket relay optimization | Already semantically ported | Candidate `aa3d96e3` ports parse-once and bounded fairness into the beta.3 reader while preserving upstream reconnect affinity, incomplete reasons, safe replay, and sequenced-replay refusal; its benchmark blob matches local `main`. |
| `876db324` performance OpenSpec archival/sync | Mixed: completed query changes archived and normative contracts ported; relay archive topology intentionally superseded | Archive the dashboard query, request-log pagination, and usage-cache changes at their current-main paths; restore non-superseded query-performance and malformed-created archive-attribution requirements in main specs. Keep this active rollback change as the current direct/HTTP relay rationale and do not reintroduce the superseded HTTP fast-path requirement. |
| `9c447c39` explicit unknown owner metadata | Missing, now semantically ported | Preserve request-log owner timestamps/session ids when proven and emit explicit `unknown` for account-only cache hits; never infer age or same-session from current scope. |
| `efa4b4fa` final formatting | Already semantically ported | The affected production and benchmark blobs match local `main`; no independent product behavior remains to port. |

This inventory leaves no unclassified local-main delta. The only intentionally omitted product implementation is the `f787f10c` HTTP scheduling fast path, whose rollback is the purpose of this change; its deterministic measurement contract remains present. Completed query changes use the current-main archive topology. The historical direct/HTTP archive copies are superseded by this richer active integration record, which carries the retained direct-WebSocket contract and the explicit HTTP rollback decision.

## Decision Rationale and Alternatives

The chosen release shape is a selective runtime restore, not a causal bug fix. Reverting only the lock would leave untested timeout, parsing, queue, and scheduling deltas. Reverting the whole commit would unnecessarily delete the HTTP benchmark. Holding every performance change would discard work outside the failing path. The selected boundary keeps beta.3 HTTP bridge scheduling byte- and semantically unchanged and retains unrelated optimizations. A benchmark observation that a ready enqueue waits behind a finite prebuffered burst is not live-safety proof and does not justify changing the production scheduler; the prior HTTP scheduling optimization remains excluded pending a separate reviewed canary.

Close attribution uses existing request-log columns. A finite reason is supplied by the caller rather than inferred from final session state. The per-request draining flag determines whether an otherwise unattributed failure can be classified as downstream; non-draining closes remain bridge lifecycle failures.

## Constraints and Failure Modes

- No database schema, migration, dependency, or configuration change is allowed. The only route delta relative to beta.3 is restoration of local `GET /api/activity/state`; no existing route or response schema changes.
- `stream_incomplete` remains visible in request logs; draining or initially unsettled cleanup is account-health neutral, while existing penalty behavior is preserved only for eligible non-draining requests after all initial reservations settle.
- Existing upstream or continuity failure metadata takes precedence and is augmented rather than replaced.
- Raw identifiers and payload content are excluded from close attribution.
- The restored runtime may still exhibit the pre-existing detach/prune race; the new metadata is intended to distinguish it during canary rather than claim it is fixed.

## Operational Notes

Before any canary, run the focused HTTP bridge and request-log tests, the deterministic HTTP benchmark, static and OpenSpec checks, and the full test suite. Treat the benchmark as deterministic routing, ownership, archive, order, cancellation, timeout, sentinel, cleanup, and timing evidence—not as live-safety evidence for a scheduler change. During canary, separate upstream abnormal closes from local bridge closes and group local closes by finite close reason and draining state. Do not interpret a draining local close as a proven client cancellation without the recorded flag, and do not infer causality from aggregate windows whose cohorts differ.

## Related Contracts

- `openspec/specs/proxy-relay-performance/spec.md`
- `openspec/specs/proxy-runtime-observability/spec.md`
- `openspec/specs/query-caching/spec.md`
- `openspec/specs/responses-api-compat/spec.md`
