# Desktop Voice owner integration

## Purpose and client contract

The explicit Desktop Voice lane is a codex-lb compatibility extension for clients that create a call using their signed-in ChatGPT identity. A separate registered gateway key controls LB admission. A trusted native verification of the caller precedes lookup of exactly one stored user/workspace owner within that key's account scope. Caller claims alone never authorize stored-token use.

The provider omits `env_key` and supplies `X-Codex-LB-Key` through `env_http_headers`, while retaining `requires_openai_auth = true`. Models and Responses continue using existing key policy and pooled routing; caller OAuth, account context and attestation are stripped before pooled upstream credential construction.

With the explicit prefix `/backend-api/codex/desktop-voice`, a WebSocket override ending in `/realtime` becomes `/live/<call-id>` for v3 or `/realtime?call_id=...` for v1. The creation override uses the prefix itself and appends `/realtime/calls`. The WebSocket suffix is significant.

## Ownership, privacy and failure behavior

Caller verification uses a bounded read at a fixed trusted origin, without redirects or retries. Native creation uses `https://chatgpt.com/backend-api/wham/realtime/calls`; native sideband uses the fixed `wss://api.openai.com/v1` base. Ordered query parameters, supported protocol/context fields and attestation are preserved only for verified native Voice egress.

For example, an exact matching PAUSED owner may serve its authenticated user's Voice request while remaining PAUSED and excluded from ordinary model-pool selection. Missing, ambiguous, out-of-scope, expired or unavailable owners fail closed; the lane does not substitute another account. Existing refresh behavior must preserve the exact principal and pause status.

The [native app-server producer](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/app-server/src/attestation.rs#L148) emits compact version-one JSON attestation. Strict envelope parsing distinguishes JSON punctuation from arbitrary credential lists while retaining the single-header and 16 KiB limits. Attestation never grants identity or authorization. Rejection diagnostics contain only fixed reasons and transport/lane labels; live call identifiers, credentials, SDP and frames remain excluded from persistence and tracing.

## Configuration and rollback

Back up the existing client configuration before replacing provider authentication and setting the two explicit Voice URLs. Sign in to ChatGPT and ensure the same user/workspace exists as an eligible stored LB owner within the registered key's scope. Reload the client configuration, using a fresh chat or cold restart when an existing chat retains provider state.

Keep the previous configuration and server image available for rollback. No schema migration is required. Restore the previous configuration and image if verification fails.

## Product verification

An actual Desktop session verified model traffic, microphone input, transcription, delegated Codex work and audible output. LB accepted its exact-owner sideband. That mode creates the native call directly from Desktop and does not proxy WebRTC media. Silent transport probes alone do not establish audio or delegation, and the legacy app-server creation route has separate test coverage.
