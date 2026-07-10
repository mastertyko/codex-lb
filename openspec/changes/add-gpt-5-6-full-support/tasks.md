## 1. Model catalog and aliases

- [x] 1.1 Add exact GPT-5.6 Sol, Terra, and Luna bootstrap metadata and WebSocket preference with focused registry tests.
- [x] 1.2 Add the official `gpt-5.6` to Sol alias across registry behavior lookups, request normalization, allowlists, and pricing identity.
- [x] 1.3 Add 128,000 max-output metadata and route-level assertions for both OpenAI-compatible and Codex-native model catalogs.

## 2. Prompt caching and usage

- [x] 2.1 Recognize and validate explicit Platform cache controls during Chat translation, then strip them at the shared subscription-upstream serializer while retaining existing sanitation, instruction lifting, and `prompt_cache_key`.
- [x] 2.2 Type and preserve `cache_write_tokens` through Responses HTTP/SSE/WebSocket parsing and Responses-to-Chat usage translation.
- [x] 2.3 Add route-level tests proving Platform-only cache options/breakpoints do not reach the subscription upstream while cache-write usage still reaches settlement paths.

## 3. Pricing and accounting

- [x] 3.1 Add canonical and alias GPT-5.6 standard and long-context price entries with exact-threshold tests.
- [x] 3.2 Split ordinary input, cached-read, and cache-write token buckets; apply the 1.25x write multiplier and clamp overlaps.
- [x] 3.3 Prove persisted request cost and API-key cost quota settlement include cache-write charges for HTTP and WebSocket completions.

## 4. Reasoning policy surfaces

- [x] 4.1 Add `max` to API-key backend schemas/service validation and create/update/enforcement tests.
- [x] 4.2 Add `max` to API-key React schemas and create/edit selectors without advertising `ultra` as a wire effort.
- [x] 4.3 Add `max` to dashboard model-policy metadata and automation backend/frontend schemas and selectors, filtering native-only `ultra`.

## 5. Integration verification

- [x] 5.1 Add public HTTP Responses and Chat Completions tests for GPT-5.6 canonical/alias forwarding and cache controls.
- [x] 5.2 Add downstream WebSocket `response.create` tests for GPT-5.6 alias, max effort, transport preference, and cache-write accounting.
- [x] 5.3 Run focused backend and frontend suites, then full backend lint/type/test and frontend lint/type/test/build gates.

## 6. Specification verification

- [x] 6.1 Run strict OpenSpec change and repository validation; reconcile implementation, tests, and change artifacts.
- [x] 6.2 After explicit authorization, run a parallel Mac mini smoke with copied data, preserve rollback anchors, cut over the live image, and verify real GPT-5.6 traffic.

## 7. Native Responses Lite passthrough

- [x] 7.1 Amend this GPT-5.6 OpenSpec change so `responses-api-compat` normatively covers native Responses Lite payload fidelity and per-transport signaling from issue #1157 / PR #1158.
- [x] 7.2 Preserve lite-shaped array `input` during Responses normalization by bypassing instruction lifting for `additional_tools` and leaving non-lite instruction lifting unchanged.
- [x] 7.3 Detect native lite requests from the inbound header or websocket `client_metadata`, forward the signal per transport (HTTP initial/retry/compact header; upstream websocket `client_metadata`), and keep non-native stripping.
- [x] 7.4 Add focused regression coverage and strict OpenSpec validation for native/non-native HTTP, compact, and websocket Responses Lite forwarding.
- [x] 7.5 Tighten this change's design and `responses-api-compat` contract so only native Codex identity headers authorize Responses Lite, copied/non-native metadata is stripped, and trusted truthy signals canonicalize to `"true"`.
- [x] 7.6 Finish the proxy hardening and make the new non-native body-metadata plus trusted-header-precedence regressions pass across HTTP, compact, and websocket forwarding.
- [x] 7.7 Correct the compact Lite contract: inspect the validated raw signal before compact serialization, emit only the canonical HTTP header, and retain compact's existing removal of all `client_metadata`.
- [x] 7.8 Make native metadata-only and untrusted/falsey compact regressions pass without an extra full-payload copy.

## 8. PR #1161 body-derived Lite parity

- [x] 8.1 Update this GPT-5.6 OpenSpec change so the final `responses-api-compat` Lite contract is body-authoritative, strips inbound internal markers, derives canonical transport signaling, and keeps section 7 as historical context.
- [x] 8.2 Implement body-derived Lite detection and split HTTP/WebSocket signaling without reviving header-only or metadata-only authorization.
- [x] 8.3 Preserve `additional_tools` plus the adjacent developer message through compact trimming while keeping compact `client_metadata` omitted and signaling Lite only via the canonical HTTP header.
- [x] 8.4 Preserve the derived Lite flag through the HTTP bridge's trim/retry/fallback paths so upstream HTTP attempts keep the canonical header without reusing stale inbound markers.
- [x] 8.5 Allow marker-only incremental websocket continuity only after upstream `response.created` accepts the same effective model after alias/API-key enforcement, and clear that trust on prewarm, rejection, model change, or API-key change.
- [x] 8.6 Add focused regressions and validation for body-only HTTP, stale-marker stripping, HTTP vs websocket signaling split, compact oversize trimming, bridge retry/fallback, and websocket trust continuity.
