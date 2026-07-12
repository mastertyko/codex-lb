## Context

The persistent HTTP Responses bridge optimization in local commit `f787f10c` changed the pending lock, timeout, parsing, queue, and scheduler behavior. Upstream `v1.21.0-beta.3` does not contain that optimization and already uses the conservative scheduling bundle, while adding admission-waiter recovery, unanchored-lane isolation, reconnect affinity, incomplete-reason fidelity, safe replay, and sequenced-replay refusal. The integration must retain those upstream source shapes rather than restore pre-beta files wholesale.

The release candidate therefore keeps beta.3's HTTP runtime unchanged, reapplies non-overlapping core and usage optimizations, ports the measured direct-WebSocket parse-once/bounded-fairness delta into the current upstream reader, and layers finite close attribution plus shared cleanup ownership on top. Request logs already expose nullable `failure_phase` and `failure_detail`, so no database or response schema change is necessary.

History reconciliation adds a second integration constraint: the verified candidate tree must first absorb every non-superseded local-main contract without replacing beta.3's overlapping continuity implementations. The activity endpoint is restored as an isolated module/router/repository read path; stale-anchor diagnostics are derived from beta.3 request state and owner records only on fail-closed paths; already-implemented query and archive-attribution requirements are synchronized into main specs.

## Goals / Non-Goals

**Goals:**

- Preserve beta.3's HTTP bridge scheduling, parsing, timeout, queue-delivery, admission-waiter, and lane-isolation semantics as one coherent baseline.
- Reapply each non-duplicated measured core, usage, and direct-WebSocket optimization plus every deterministic benchmark entrypoint without replacing overlapping upstream files.
- Make every local bridge session-close failure attributable to a finite close reason and the request's actual draining state.
- Preserve `stream_incomplete`, request-specific failure overrides, and privacy boundaries while preventing draining-only local closes from mutating account health and preserving the existing single non-draining penalty only after reservation settlement.
- Keep the HTTP benchmark behaviorally representative of production after the restore.
- Restore local-main activity polling, stale-anchor diagnostics, query-performance requirements, and malformed-created archive attribution without changing beta.3 replay eligibility or hot-path scheduling.

**Non-Goals:**

- Claim that the optimized relay caused the canary failures.
- Use benchmark ready-task timing as evidence to change beta.3 HTTP relay scheduling without a separate reviewed canary.
- Suppress, reclassify away, or retry `stream_incomplete` failures.
- Change database schemas, dependencies, bridge admission, routing, idle TTL, durable ownership, or public APIs beyond restoring local `GET /api/activity/state`.
- Weaken or replace beta.3 admission, reconnect-affinity, incomplete-reason, owner-replay, sequence, migration, version, dependency, or unrelated release behavior.
- Build, deploy, push, or canary the candidate; history reconciliation is limited to a local candidate-first merge whose tree is proven identical to the verified pre-merge candidate.

## Decisions

### Retain the beta.3 HTTP bridge runtime bundle atomically

Beta.3 already uses the default AnyIO pending lock, `asyncio.wait_for` receive and event-queue waits, eager event parsing and previous response/error derivation, awaited queue puts, and no explicit frame-count scheduler checkpoint. Keep that implementation and its production `rewrite_parallel_tool_call_text` caller unchanged. The retained deterministic benchmark measures production routing, ownership, archive attribution, order, cancellation, contention, receive timeout, terminal sentinels, cleanup, and throughput; it MUST NOT require a ready enqueue to run before a finite prebuffered burst drains or treat such timing as live-safety proof. The prior HTTP scheduling optimization remains excluded pending a separate reviewed canary. The local rollback contributes its deterministic HTTP benchmark and corrected cleanup/attribution contracts, not a historical bridge-file replacement or a new scheduling bundle.

Alternative: replay `d1d02044` or restore files from the pre-beta branch. Rejected because that would overwrite upstream admission-waiter, lane-isolation, replay, and affinity work even though the runtime rollback is already satisfied.

### Use one finite close-reason type through every close path

Define one private `Literal` close-reason type and require `_close_http_bridge_session`, its bounded wrapper, and its scheduler to receive it. Production reasons are `account_binding_changed`, `capacity_evict`, `creation_aborted`, `idle_prune`, `local_terminal_error`, `registry_detach`, `retire_after_drain`, and `shutdown`. Each existing production close callsite selects the reason that caused that close; idle pruning is no longer collapsed into generic registry detachment.

Alternative: infer a reason inside `_close_http_bridge_session` from mutable session state. Rejected because multiple close causes can produce the same final state and inference would corrupt canary attribution.

### Preserve shared settlement and exactly-once finalization through cancellation

`_fail_pending_websocket_requests` is the shared cleanup path for WebSocket-backed pending requests from both the persistent HTTP bridge and direct downstream WebSocket transport. Finite close-reason attribution remains HTTP-bridge-specific, while reservation-first settlement ordering, draining and initially-unsettled health neutrality, partial-release batch retry, foreground ownership transfer, exactly-once finalization, and shutdown cancellation to quiescence are unconditional shared behavior.

While holding the existing pending lock, snapshot every remaining request, append HTTP close metadata when supplied, and synchronously take and clear each request's API-key reservation ownership. Before releasing the lock, create exactly one finite-prefix post-take child for the complete release, retry-transfer, health, and finalization phase and adopt that already-created task through the shared cancel-safe cleanup tracker; it is the only background-registry owner for the phase. Await the child through `asyncio.shield`, so foreground reader-owner cancellation propagates only after the child is already retained. The child attempts every non-null initial release independently without an inner cancellation shield. A cancelled or failed initial release makes the batch unsettled and transfers that opaque request/reservation pair to the independently necessary sequential retry task; later initial releases still run and health remains neutral. For each health or request finalizer, invoke its coroutine factory exactly once to create one local operation task, then repeatedly await that same local task through `asyncio.shield` after post-take cancellation. Do not register the local task independently: the tracked parent cannot exit before consuming its single terminal result. This prevents duplicate gate releases, queue signals, terminal sends, health writes, and request logs. Because cancellation never reaches the local `_write_request_log` operation task, its shielded `_persist_request_log` task finishes normally instead of being transferred alive into `_request_log_tasks`.

Only the post-take child and an independently necessary reservation batch retry use finite transport-neutral action prefixes in `_background_cleanup_tasks`; local finalizer operation tasks have no independent registry ownership or shutdown task class. The shutdown drain repeatedly snapshots the HTTP close, post-take, and retry classes against one absolute deadline. At the deadline, a post-take task is explicitly cancelled and terminally awaited through the existing helper; its cancellation-safe state transition transfers any interrupted reservation and repeatedly awaits its current already-created local finalizer task without reinvoking the operation. Because the tracked parent cannot terminate first, shutdown ownership of that one parent also owns the local operation and prevents cancellation from entering `_write_request_log`. The drain then rescans and explicitly cancels and terminally awaits every retry task produced by completion before returning to database teardown, with both `_background_cleanup_tasks` and `_request_log_tasks` quiescent for this cleanup path. Existing close-task timeout handling remains unchanged.

An upstream reader branch that invalidates its socket must commit `upstream_control.reconnect_requested = True` before awaiting pending-request failure finalization, because that await publishes client-visible terminal events and the downstream may submit a follow-up immediately. This ordering applies to fail-all receive timeout, unreplayable upstream close, and reader crash. Transparent replay already commits reconnect and replay state before returning without terminal failure; per-request expiry intentionally keeps the upstream; downstream-disconnect paths terminate the downstream and must not force reconnect merely because they finalize pending requests.

Alternative: filter draining requests out of the cleanup list. Rejected because that would hide failures and skip terminal/log finalization. Alternative: release each reservation inside the later finalization loop. Rejected because a selected health mutation could observe stale reserved capacity and detach/close races could retain duplicate ownership. Alternative: abort on the first release exception. Rejected because later reservations and every request finalizer would be skipped after ownership had already been cleared. Alternative: schedule one background task per failed reservation. Rejected because a database outage could fan out unbounded tasks across the entire pending batch. Alternative: make the batch task HTTP-specific or leave it outside shutdown ownership. Rejected because direct WebSocket cleanup can create the same task and database teardown must not race its retry. Alternative: restore failed ownership to the request state. Rejected because detach/close cleanup could then double-release it; failed ownership instead moves exactly once to the bounded batch retry.

### Retain the benchmark and rebaseline only legitimate payload changes

Keep the real HTTP relay benchmark on beta.3 production scheduling and retain finite prebuffered-burst routing and ownership, archive attribution, order, cancellation, contention, receive timeout, terminal sentinel, cleanup, fast-consumer, and backlogged-consumer checks. Remove the ready-enqueue scheduling assertion and update the locked digest only because its correctness payload no longer includes that assertion; update timing references only when a measured beta.3-runtime baseline justifies it.

### Layer local-main contracts around authoritative beta.3 continuity state

Keep beta.3's replay refusal, full-resend safety, reconnect affinity, incomplete-reason, and sequence rules as the behavior source of truth. Add stale-anchor fields to the existing request state only to record accepted-anchor provenance, request-log owner metadata, replay availability from the current safety predicate, age, and same-session status. Account-only cache hits cannot prove row metadata, so they remain explicit `unknown`; no field may alter replay eligibility or expose a raw anchor.

Restore `GET /api/activity/state` through the existing dependency/provider and API router patterns. Its repository query aggregates only the requested warmup-excluded window, while the service owns deterministic scoring and stale-cache fallback. This isolation keeps the performance candidate's relay/query hot paths unchanged. Synchronize the already-implemented query-cache and malformed archive-attribution contracts into main and active specs rather than copying the local performance archive topology or the superseded HTTP fast-path requirement.

Alternative: cherry-pick the activity and stale-diagnostic commits wholesale. Rejected because the activity commit's router and repository pieces are portable but its archived OpenSpec topology is not the active source of truth, while the stale-diagnostic commit predates beta.3's owner/replay structures and would overwrite authoritative upstream behavior.

## Risks / Trade-offs

- Restoring the default lock increases relay CPU/scheduler cost → accept the measured cost for release safety and continue reporting it through the retained benchmark.
- Close attribution could overwrite a more specific upstream diagnostic → append the close fragment and preserve existing phase/detail overrides.
- A close callsite could omit or invent a reason → make the finite reason argument required and cover representative draining and non-draining paths.
- A detach/close race could double-release a request reservation or mutate health against stale capacity → take and clear reservation ownership synchronously under the pending lock, release outside the lock, and keep release idempotent when ownership is already gone.
- Cancellation during an ambiguous finalizer await could duplicate a terminal send or log, or transfer a live request-log persist task beyond shutdown → create each operation task once as a local child of the sole tracked post-take task, repeatedly shield-await only that same local task, consume one result, and defer post-take cancellation until terminal completion. Never add a separate finalizer registry owner or drain class; parent terminality is the ownership boundary that leaves both cleanup registries empty before database teardown.
- Benchmark timing can vary by host load → lock only correctness payload changes and report timing as repeated median/p95 measurements.
- The observed canary issue may recur after the restore → keep live deployment out of this change and require an independently audited canary with close-reason breakdown.

## Migration Plan

1. Verify the annotated beta.3 tag target and GitHub-signed release commit, then map overlapping upstream PRs and local commits.
2. Create a focused branch at the verified tag and reapply only non-overlapping core, usage, relay, benchmark, attribution, and cleanup deltas.
3. Inventory every local-main-only commit and classify its deltas as upstreamed, semantically ported, intentionally superseded, or missing before editing or merging.
4. Port missing activity, stale-anchor, query-spec, and archive-attribution contracts around beta.3 source shapes; restore focused coverage; then run affected relay suites and final static/spec/migration/full gates.
5. Preserve the already-verified four benchmark digests unless a contract-preservation edit changes a measured product hot path; activity aggregation and failure-only stale diagnostics do not change those benchmark paths.
6. Commit the verified preservation work, record the candidate tree, create a candidate-first local history-reconciliation merge with prior `main` as the second parent, fast-forward local `main`, and prove exact tree identity without push, deploy, or canary work.

## Open Questions

None. Production causality remains explicitly unproven and is an observation for the future canary, not a design assumption.
