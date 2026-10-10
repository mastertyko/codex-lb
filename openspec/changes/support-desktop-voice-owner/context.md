# Desktop Voice compatibility context

## Credential boundary and native attestation

Desktop can use its signed-in ChatGPT identity to create a Voice call while the proxy uses a registered LB key for admission. The explicit Desktop Voice lane verifies that caller against a fixed trusted native endpoint and selects only the matching stored user and workspace. Existing pooled call bindings remain separate.

The native app-server wraps attestation metadata in compact JSON containing `v`, `s` and, on success, `t`. The commas in this envelope previously triggered the unsupported credential-list check, causing ordinary Responses and Voice requests to fail before owner selection. The repair accepts the bounded, documented envelope grammar and preserves all gateway-key, caller and owner checks. The envelope is metadata, never an identity or authorization source. See the [native producer](https://github.com/openai/codex/blob/740e5af33c71225640e0c1c1555c514c2c93ab74/codex-rs/app-server/src/attestation.rs#L148).

Gateway rejection diagnostics expose only fixed categories and transport/lane labels. They retain the generic public denial and do not contain request values, identities, lengths or exception text.

## Verification evidence and limits

A real Codex Desktop session verified an ordinary model reply, microphone input, transcript delivery, a delegated system-version check and audible playback. Server evidence confirmed admission of the Desktop Voice sideband after the exact-owner checks and lease acquisition. In that client mode, native call creation and WebRTC media travel directly between Desktop and ChatGPT; they are not proxied by LB. The explicit app-server creation route is covered separately by integration tests.

The publication candidate is extracted onto current public upstream main. Private runtime history, deployment manifests and unrelated changes are excluded. Prior runtime evidence establishes product behavior, while focused tests, the full repository local gate and independent review separately verify this public candidate.

## Related work

- [Codex Live Voice sideband](https://github.com/Soju06/codex-lb/pull/1492) provides the existing pooled-call workflow.
- [Live cancellation through lease release](https://github.com/Soju06/codex-lb/pull/1986) provides the existing lease lifecycle.
- [support OAuth callers for Codex Live Voice](https://github.com/Soju06/codex-lb/pull/1577) was closed without merging. This extension retains registered-key admission, verified caller identity, attribution and revocation rather than admitting keyless OAuth requests.
- [docs: explain Codex Desktop voice endpoint configuration](https://github.com/Soju06/codex-lb/pull/2562) discusses client endpoints. This change documents the distinct authenticated Desktop lane.
