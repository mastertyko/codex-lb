# HTTP Bridge Fast-Path Rollback Context

## Purpose and Scope

This change prepares a conservative measurable-performance candidate on verified upstream release commit `a225f0db0c3e00224d3f4256590d5d05dfa763d4` (`v1.21.0-beta.3`). It retains the release's overlapping HTTP bridge and direct-WebSocket fixes, preserves the release's already-restored HTTP runtime semantics, reapplies only non-duplicated measured optimizations, and adds failure-only attribution plus shared cleanup guarantees. Normative behavior is defined in the delta `spec.md` files; this document records rationale, overlap evidence, and operational context.

## Observed Evidence

The canary recorded four HTTP-to-WebSocket `stream_incomplete` rows among 82 requests. One was an upstream abnormal close at approximately 13.3 seconds. Three were local bridge session closes at approximately 123 seconds, close to the configured 120-second idle TTL. All four belonged to one sanitized cohort that was absent from both comparison windows. Prior `8c17e62c` traffic recorded one incomplete row among 318 requests; an equal restored window recorded zero among 22.

A deterministic detach/prune/close harness reproduced the local bridge-close record with both AnyIO's default pending lock and `fast_acquire=True`. The harness proved a plausible misattribution path but did not prove that the optimized runtime caused the live failures or that the live requests followed that path.

## Upstream Beta.3 Overlap Evidence

The fetched annotated tag resolves locally to `a225f0db0c3e00224d3f4256590d5d05dfa763d4`; GitHub marks that commit's PGP verification as valid. The tag object itself is unsigned, so commit verification and the official release target are the trust evidence. Official beta.3 notes include HTTP admission-waiter recovery (#1191), unanchored bridge isolation (#1169), WebSocket reconnect affinity (#1220), incomplete-reason fidelity (#1219), safe turn reselection and owner replay (#1207), and sequenced-replay refusal (#1223).

Those upstream implementations supersede the older local sequence/replay and broad source shapes and must remain authoritative. The local core parser, SSE, balancer, chat-mapping, usage-query, and deterministic benchmark paths have no upstream changes after the shared base and remain non-duplicated. The local `f787f10c` HTTP fast path is not present in beta.3, so the rollback is satisfied by retaining beta.3's current HTTP scheduling implementation rather than copying older bridge files. Finite close attribution and the shared reservation/health/finalization/shutdown contract remain absent and are reapplied semantically on top.

## Decision Rationale and Alternatives

The chosen release shape is a selective runtime restore, not a causal bug fix. Reverting only the lock would leave untested timeout, parsing, queue, and scheduling deltas. Reverting the whole commit would unnecessarily delete the HTTP benchmark. Holding every performance change would discard work outside the failing path. The selected boundary keeps beta.3 HTTP bridge scheduling byte- and semantically unchanged and retains unrelated optimizations. A benchmark observation that a ready enqueue waits behind a finite prebuffered burst is not live-safety proof and does not justify changing the production scheduler; the prior HTTP scheduling optimization remains excluded pending a separate reviewed canary.

Close attribution uses existing request-log columns. A finite reason is supplied by the caller rather than inferred from final session state. The per-request draining flag determines whether an otherwise unattributed failure can be classified as downstream; non-draining closes remain bridge lifecycle failures.

## Constraints and Failure Modes

- No database schema, migration, dependency, public API, or configuration change is allowed.
- `stream_incomplete` remains visible in request logs; draining or initially unsettled cleanup is account-health neutral, while existing penalty behavior is preserved only for eligible non-draining requests after all initial reservations settle.
- Existing upstream or continuity failure metadata takes precedence and is augmented rather than replaced.
- Raw identifiers and payload content are excluded from close attribution.
- The restored runtime may still exhibit the pre-existing detach/prune race; the new metadata is intended to distinguish it during canary rather than claim it is fixed.

## Operational Notes

Before any canary, run the focused HTTP bridge and request-log tests, the deterministic HTTP benchmark, static and OpenSpec checks, and the full test suite. Treat the benchmark as deterministic routing, ownership, archive, order, cancellation, timeout, sentinel, cleanup, and timing evidence—not as live-safety evidence for a scheduler change. During canary, separate upstream abnormal closes from local bridge closes and group local closes by finite close reason and draining state. Do not interpret a draining local close as a proven client cancellation without the recorded flag, and do not infer causality from aggregate windows whose cohorts differ.

## Related Contracts

- `openspec/specs/proxy-relay-performance/spec.md`
- `openspec/specs/proxy-runtime-observability/spec.md`
- `openspec/changes/archive/2026-07-12-optimize-http-bridge-relay-lock/`
