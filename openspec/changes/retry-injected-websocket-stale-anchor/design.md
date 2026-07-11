## Context

Direct Responses WebSocket requests can carry either a client-supplied `previous_response_id` or a proxy-injected session-continuity anchor. For full-context turns, codex-lb can retain a no-anchor request body that is safe to replay if upstream rejects the injected anchor. The existing continuity path also handles owner-pinned reconnects, pre-created requests that close before any `response.*` event, Codex prewarm traffic, and HTTP compact calls. These paths share request state, request logging, account-health settlement, and bounded request budgets.

## Goals / Non-Goals

**Goals:**

- Prefer an already-prepared, retry-safe no-anchor body when upstream rejects a stale WebSocket anchor.
- Keep short client-supplied continuations owner-bound and limit replay to one attempt before any `response.*` event.
- Fail closed after `response.created` unless a retry-safe no-anchor body exists, and record why replay was refused.
- Preserve Codex `request_kind` in request logs while preventing empty prewarm completions from counting as user-turn success or continuity ownership.
- Bound compact upstream calls by the remaining proxy compact request budget.

**Non-Goals:**

- Retrying arbitrary client continuations without a self-contained fresh body.
- Moving a previous-response continuation to a different account.
- Changing public response envelopes or adding database columns.
- Treating prewarm completion as user-visible turn progress.

## Decisions

### Keep replay eligibility explicit on request state

The WebSocket request state retains the original anchored payload together with an optional fresh no-anchor payload and a boolean that records whether the fresh payload is retry-safe. Stale-anchor handling consults these fields instead of reconstructing or guessing replay safety after an upstream error.

Alternative considered: remove `previous_response_id` from the current payload at failure time. Rejected because a short continuation may not contain enough context to produce an equivalent request.

### Resolve retry-safe stale anchors before owner-unavailable handling

`previous_response_not_found` first uses the prepared fresh payload when one is marked retry-safe. Preferred-owner unavailable rewriting applies only when no safe fresh replay exists. This ordering prevents an available recovery path from being hidden by owner pinning.

Alternative considered: retry the anchored request on the preferred owner first. Rejected because upstream has already declared that anchor missing and repeating it cannot restore continuity.

### Keep pre-created short continuation replay owner-bound

A client-supplied continuation may replay once on the same owner only when the connection closes before any `response.*` event. Once `response.created` or later output exists, replay is refused unless a retry-safe fresh body is available. Refusal reasons are carried into request-log failure metadata.

Alternative considered: exclude the failed owner and retry another account. Rejected because previous-response identifiers are account-owned and cross-account replay breaks continuity.

### Classify prewarm settlement separately

Codex turn metadata is parsed once and persisted as `request_kind`. An empty `prewarm` completion may pass through to the client, but it does not mark the account successful and does not establish previous-response ownership.

Alternative considered: settle every `response.completed` event identically. Rejected because an empty prewarm frame proves transport availability, not successful user-turn execution.

### Derive compact timeouts from the remaining request budget

Compact calls receive connect and total timeout overrides bounded by the remaining proxy compact budget even when no explicit upstream compact timeout is configured. Existing request-log metadata records `request_kind=compaction`.

Alternative considered: rely only on the HTTP client's default timeout. Rejected because that timeout can outlive the proxy request budget and wedge automatic compaction.

## Risks / Trade-offs

- A payload incorrectly marked retry-safe could duplicate or change a turn. Mitigation: only request preparation may set the flag, and replay is limited to one attempt before downstream-visible output.
- Replaying a short continuation on another account would violate response ownership. Mitigation: retain the preferred owner and do not add it to the exclusion set for the bounded replay.
- Response-event accounting mistakes could replay after upstream created a response. Mitigation: count `response.*` events and fail closed after creation without a safe fresh body.
- Prewarm classification could suppress valid account settlement if metadata is wrong. Mitigation: apply the special case only to explicit `request_kind=prewarm` with empty output.
- A nearly exhausted compact budget can produce an immediate timeout. This is intentional: returning a bounded failure is safer than exceeding the proxy deadline.

## Migration Plan

No schema or data migration is required. Deploy the proxy and request-log changes together. Existing requests without Codex turn metadata keep their prior classification. Rollback consists of reverting the application change; persisted request logs remain compatible because the added metadata uses existing fields.

## Open Questions

None.
