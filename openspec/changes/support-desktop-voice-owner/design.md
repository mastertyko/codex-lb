## Context

Desktop can create native calls independently of the configured model provider. Its unchanged app-server can send a ChatGPT bearer and an environment-sourced registered gateway key simultaneously. Existing Live routes intentionally require LB-created bindings. The implementation extends that existing registered-key policy to an explicit Desktop lane; it does not weaken the pooled binding contract or claim parity with OpenAI authentication.

## Goals / Non-Goals

**Goals:** Route Desktop Voice through the existing LB using the exact matching stored user/workspace account; dynamically follow the caller's authenticated identity; allow that account to remain paused for pooled model use; keep ordinary pool traffic and existing call bindings unchanged.

**Non-Goals:** A new local proxy, patched Codex binary, arbitrary account selection, unsigned claims as authorization, keyless OAuth admission, a public Realtime API, migrations or automatic unpausing.

## Decisions

1. Keep provider-id `codex-lb`. Use `requires_openai_auth=true`, remove provider `env_key`, and carry the existing LB-key in `X-Codex-LB-Key` through `env_http_headers`. Voice base URLs point to explicit private Desktop Voice routes on LB; Models/Responses retain their existing routes. The key header must never go to OpenAI.
2. At a narrow ASGI credential boundary, require exactly one nonempty gateway-key and one caller bearer, validate the registered LB-key even when ordinary auth is globally off, and replace pool-facing Authorization with LB auth. Hold caller Voice credentials only in a typed request-state value with secret fields excluded from repr. Remove caller account/auth/attestation from ordinary pool paths and remove the gateway header from every upstream path, including specialized transcribe handling. Reject ambiguous duplicates before any upstream request.
3. For the new Voice lane only, require exact user and workspace claims from the caller access token. Claims are initially an untrusted selector. Authenticate the exact same bearer through a bounded GET to the fixed native usage endpoint: strict 200, expected JSON shape, no redirects or retries, no response/exception detail logging, and existing egress policy. Only after upstream accepts that bearer are its claims treated as authenticated. The existing permissive usage parser is not reused as the authentication gate.
4. Match both user and workspace to exactly one nondeleted LB account, enforce the proxy key's assignments, then freshly reload and recheck identity/state before stored-token use. Missing/ambiguous identity, mismatch or account mutation fails closed. Preserve caller installation/protocol context for externally created calls. Stored-token expiry/refresh must preserve the exact principal and pause state; no refresh retry after a failed call attachment and no other account or caller-token fallback.
5. Pool pause and caller-owned Voice have separate documented policies. The explicit authenticated lane accepts ACTIVE/PAUSED exact owners while existing pool and old Live selection continue excluding PAUSED. Acquire/release an exact-owner stream lease without normal pool selection; deactivated, deleted, or other unavailable states remain denied.
6. Reuse existing bounded Live relay and native connector lifecycle contracts. Add private native creation for legacy app-server-owned sessions with the same selected owner. Never insert an unverified external call into the old binding namespace and never treat old `binding_missing` as permission to use the new lane.

## Risks / Trade-offs

- Different OAuth sessions for the same principal may be rejected by native Live. Verify with a bounded real session; report this precisely if it fails rather than switching accounts or silently changing credential provenance.
- Caller identity verification adds one bounded request per Voice start. Omit caching initially to keep revocation and identity semantics simple.
- The gateway receives caller OAuth. Keep it out of logs, database, exception chains, telemetry payloads and Responses egress; test real middleware ordering and specialized header builders.
- A shared Team workspace is not a user identity. Match both fields, never email or first workspace match.
- App updates may change private Voice routes. No app binary patch will be overwritten, but retain contract tests for both creation modes and live verification after protocol changes.

## Migration Plan

Verify local code/spec/tests and independently review the exact candidate against current main. Install the server change before applying the optional Desktop configuration. Preserve the previous client config and server image for rollback, and keep account pool pause state unchanged. A real Desktop Voice session must confirm audio, transcript and delegation while Responses continue through LB. Rollback restores the previous image/config without schema changes.

## Compatibility evidence

An actual Desktop session verified model replies, the authenticated LB sideband, microphone/transcript, a delegated system-version check and audible playback. The current Desktop-owned creation mode calls its ChatGPT API directly; its successful creation is not presented as LB-proxied WebRTC media. Integration tests separately cover the supported app-server-owned creation route. Fresh or cold-resumed Desktop sessions load changed provider and Voice settings; changing a config file is not proof that an already loaded session has reloaded it.
