# Design

## Context

codex-lb already has bounded stale-anchor recovery. It can replay a verified
self-contained body without the expired anchor, or return a sanitized canonical
classifier when only a dependent delta exists. Production exposed an upstream
envelope variant where `error.type = "invalid_request_error"` and the precise message
is `Invalid \`previous_response_id\`.`, but `error.code` and `error.param` are absent.
The WebSocket parser discarded `error.type` for classifier purposes, so neither safe
server replay nor canonical client recovery ran.

Compatible clients retain canonical full conversation history while sending an
anchored delta. When they receive `previous_response_not_found`, they clear the failed
continuation and rebuild a full request. codex-lb therefore must not synthesize
missing tool history; it must preserve the existing delta fail-closed boundary and
expose the canonical classifier.

The recovery audit also found that the request state treats retry safety as proof that
the same body may move accounts. Encrypted reasoning, server-assigned ids, hosted
state, and unknown fields can be safe to resend on their owner while remaining unsafe
to send elsewhere.

## Decisions

### Normalize precise code-less stale envelopes

For WebSocket error classification, use the explicit `error.code` when present and
fall back to the normalized `error.type` only when the code is absent. The core stale
classifier remains narrow:

- canonical `previous_response_not_found` is accepted;
- `invalid_request_error` plus the exact normalized invalid-anchor message and absent
  `param` is accepted;
- structured not-found behavior remains unchanged;
- near matches, unrelated parameters, and unrelated invalid requests are rejected.

All accepted variants use the existing canonical downstream recovery code. No new
public error code is introduced.

### Keep retry safety separate from account portability

The existing `fresh_upstream_request_is_retry_safe` keeps its current meaning.
Immediately before an account-movement boundary, codex-lb parses the exact candidate
wire body, removes only the WebSocket `response.create` envelope discriminator, and
applies `responses_payload_is_account_neutral_fresh_replay()`. This avoids a second
stateful proof flag that could drift from request text while ensuring a proof for a
projected body never authorizes sending the raw body.

### Enforce portability only at account-movement boundaries

Same-account replay continues to use retry-safety, visibility, and replay-count
guards. Any retry, fallback, auth recovery, quota recovery, model reroute, or
security-work reroute that changes accounts additionally requires the selected
candidate body's portability proof.

When stale recovery removes an anchor from a nonportable body, the previous account
remains mandatory. If that owner is unavailable, the request fails closed with a
sanitized continuity error rather than moving the body.

HTTP bridge raw and projected candidates retain independent proofs. HTTP-to-WebSocket
fallback applies the same canonical portability predicate to the exact fallback
payload.

## Alternatives considered

### Retry every invalid request without the anchor

Rejected because unrelated invalid payloads could be replayed and dependent deltas
would lose context.

### Match stale anchors only by message text

Rejected because it ignores an available conflicting error classification. The
fallback requires the normalized invalid-request type and an exact message.

### Treat every retry-safe body as account-neutral

Rejected because retry safety proves delivery equivalence, not account ownership.

### Persist portability booleans beside candidate text

Rejected after regression testing because request states are copied and reconstructed
at many replay seams. A second mutable proof flag drifted from historical request
text and broke established recovery paths. Validating the exact outgoing body at the
single account-switch seam is smaller and fail-closed.

### Patch client task handling

Rejected. Compatible clients correctly emit tool results and retain full history.
The observed failure is the server's missing canonical classifier. A client-side
defense-in-depth message fallback may be pursued independently, but is not required
for codex-lb interoperability once the canonical contract is restored.

## Verification

- Unit-test exact and near-match classifier variants.
- Test full-resend server recovery and delta-only canonical client recovery using the
  observed code-less envelope.
- Test retry-safe but nonportable bodies on stale, auth, model, quota,
  security-work, bridge, and cross-transport movement seams.
- Assert raw and projected durable bodies carry independent portability proofs.
- Run full lint, type, backend, and strict OpenSpec gates.
- Deploy and exercise repeated foreground-child and background-completion
  continuations without fixed waits.
