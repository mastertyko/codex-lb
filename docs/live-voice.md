# Codex Live Voice

codex-lb keeps Codex Live Voice call creation and its control sideband on the same ChatGPT account. This matters in an account pool: the account that successfully creates a call is the only account that can safely join its sideband.

!!! note "Private Codex compatibility"
    This capability supports the private routes used by the installed Codex app. It does not implement OpenAI's public Realtime API, `POST /v1/realtime/calls`, or `POST /v1/realtime/client_secrets`, and it does not proxy WebRTC media.

## Requirement: a registered proxy key

Live Voice routes always require an existing registered [proxy API key](api-keys.md), even when ordinary proxy API-key authentication is disabled. Missing or unregistered keys are rejected before codex-lb selects or contacts an upstream account.

The existing pooled-call workflow needs no new `CODEX_LB_*` setting, migration, dependency, or setup step. The optional Desktop-owned lane below requires client configuration. Operators who do not use Live Voice can continue running the base proxy and dashboard unchanged.

## Supported private routes

A compatible Codex client uses these routes as one account-bound workflow:

- `POST /backend-api/codex/realtime/calls` creates the call.
- `WS /backend-api/codex/{call_id}` joins through the current installed-app form for bounded `rtc_...` or canonical UUID call ids; unrelated Codex WebSocket paths keep their ordinary behavior.
- `WS /v1/live/{call_id}` joins through the v3 form.
- `WS /v1/realtime?call_id={call_id}` joins through the legacy form.

codex-lb validates the call id returned in the successful call-creation `Location`, ignoring private query or fragment context after the first `?`, binds it to the final successful account under the caller's proxy key, and routes every supported sideband form back to that exact account. Attachment fails closed if the key, assignment, account state, or ownership binding is no longer valid; codex-lb does not refresh credentials or substitute another account after a call is created.

## Desktop-owned calls

Desktop clients that create a call using their signed-in ChatGPT account can use a separate explicit lane. This lane requires both a registered proxy key and a caller Bearer credential verified against the trusted native upstream. The stored LB account must match that exact user and workspace and belong to the key's allowed account scope. An exact matching PAUSED owner may serve Voice without becoming eligible for ordinary pooled model traffic.

Back up the client configuration, keep your existing model settings, and use the following provider authentication and Voice URLs. Replace `http://localhost:2455` with your LB address, export the registered key as `CODEX_LB_API_KEY`, and sign in to ChatGPT in Desktop. Omit the provider's `env_key`: the normal Bearer credential identifies the signed-in caller, while the separate header carries the LB key.

```toml
model_provider = "codex-lb"
experimental_realtime_ws_base_url = "http://localhost:2455/backend-api/codex/desktop-voice/realtime"
experimental_realtime_webrtc_call_base_url = "http://localhost:2455/backend-api/codex/desktop-voice"

[model_providers.codex-lb]
name = "openai"
base_url = "http://localhost:2455/backend-api/codex"
wire_api = "responses"
requires_openai_auth = true
supports_websockets = true
env_http_headers = { "X-Codex-LB-Key" = "CODEX_LB_API_KEY" }
```

The `/realtime` suffix on the WebSocket override is significant. Reload the configuration and test in a fresh chat; cold restart Desktop if an existing chat retains provider state. Restore the saved configuration and prior server image to roll back. No database migration is involved.

The explicit routes are `WS /backend-api/codex/desktop-voice/live/{call_id}`, legacy `WS /backend-api/codex/desktop-voice/realtime?call_id={call_id}`, and app-server creation at `POST /backend-api/codex/desktop-voice/realtime/calls`. In native Desktop creation mode, Desktop creates the call directly with ChatGPT and LB carries the verified owner's sideband. WebRTC media is not proxied. Existing pooled-call routes keep their binding requirements and never fall back to this lane.

The native version-one JSON attestation envelope is accepted with strict field, type and size checks. It does not authorize the caller. Missing or invalid credentials and owner mismatches fail closed; diagnostic logs contain only fixed rejection categories and transport/lane labels.

## Privacy and request history

The ownership record contains only an API-key-scoped digest and the owning account reference. Raw call ids, proxy keys, OAuth tokens, SDP, attestation values, and realtime frame bodies are not stored in that record. Call-creation SDP is excluded from payload traces, and sideband frames are not added to Responses archives.

The dashboard's Recent Requests data accepts the sideband as a typed `realtime_live` WebSocket request. Private call-creation and sideband rows omit account identity, model content, upstream error text, failure metadata, live query text, and credentials. The internal ownership record stays hidden from ordinary sticky-session lists and delete operations.

## Failure behavior

- `401 invalid_api_key` means the request did not carry a registered proxy key.
- `400 invalid_realtime_call_id` means the sideband supplied a malformed or ambiguous call id.
- `503 realtime_call_binding_failed` means a successful upstream call could not be bound safely; codex-lb does not replay that call through another account.

---

*Specs: [realtime-api-compat](https://github.com/Soju06/codex-lb/tree/main/openspec/specs/realtime-api-compat), [desktop-voice-owner](https://github.com/mastertyko/codex-lb/tree/feature/desktop-voice-owner/openspec/specs/desktop-voice-owner)*
