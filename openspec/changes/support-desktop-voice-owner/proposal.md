## Why

Codex Desktop now creates Voice calls using its signed-in ChatGPT identity before asking its app-server to attach a sideband. A custom LB provider currently sends only its proxy key for attachment; LB correctly rejects the unknown externally created call before using any account. Users need Voice to use the exact signed-in user and workspace while ordinary model requests continue using the pool, without patching Codex or adding another proxy.

## What Changes

- Add explicit private Desktop Voice endpoints, separated from the existing pool-created Live binding contract.
- Accept a registered LB key in a separate gateway header alongside caller OAuth, with strict duplicate handling and credential removal before pool routing.
- Verify the exact caller bearer against a fixed trusted upstream before matching both user and workspace to exactly one existing account and using that account's stored OAuth for Voice.
- Preserve API-key account scope, admission and stream caps, private logging, cancellation cleanup, and no account failover. Keep account changes fail closed if no unique eligible match exists.
- Handle pool pause independently from explicitly authorized Desktop Voice; do not silently unpause an account or broaden model routing.
- Add config instructions and regression coverage for both client-created and app-server-created Voice and unchanged pooled Responses.
- Accept the native version-one attestation envelope with strict size, field and type checks, and report credential denials using fixed privacy-preserving diagnostic categories.

## Capabilities

### New Capabilities

- `desktop-voice-owner`: Authenticated Desktop Voice identity matching, private native call routes, and their separation from pooled model traffic.

### Modified Capabilities

- `realtime-api-compat`: Clarify that externally created Desktop calls use an explicit new lane and never bypass the existing pool-call binding contract.

## Impact

Changes affect request credential admission, private proxy routes/services, exact account lookup, and existing relay lifecycle helpers. This is an opt-in codex-lb compatibility extension that continues requiring a registered gateway key. It does not add keyless OAuth access, a public Realtime API, database migrations, client binary changes, another proxy process or dashboard navigation. Ordinary provider authentication and pooled model routing remain compatible. Verification covers the credential boundary, exact-owner selection and both supported Desktop creation modes; actual microphone/audio/transcript and delegated-task behavior require a Desktop session.
