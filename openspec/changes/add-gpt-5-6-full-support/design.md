## Context

codex-lb has two related but distinct model contracts. The bundled Codex catalog is a startup fallback for ChatGPT-subscription routing and must mirror the current Codex client metadata, whose GPT-5.6 input budget is 372,000 tokens. The public OpenAI model contract separately documents a 1,050,000-token Platform context window, a 128,000-token output limit, an unsuffixed `gpt-5.6` alias to Sol, long-context pricing above 272,000 input tokens, and paid cache writes. Because codex-lb proxies the ChatGPT/Codex backend, it must not claim the larger Platform input budget on its compatibility catalog, but its cost estimator must use the published Platform price rules.

The current dynamic registry already accepts canonical slugs from a refreshed upstream snapshot, but startup metadata, direct alias lookups, WebSocket preference, max-output metadata, reasoning-policy validation, cache-write accounting, and Chat-to-Responses content translation all have GPT-5.6 gaps. The change crosses backend catalog, proxy, accounting, and dashboard code, so a coordinated design is required.

Issue #1157, upstream PR #1158, and the selected PR #1161 head `1eb47a80f71b8f906bfc2bd3a54dacf8f2b2c38a` confirm a separate native Responses Lite contract gap: truthful GPT-5.6 Codex traffic can lose its `additional_tools` bundle or per-transport lite signal before upstream forwarding. That wire-contract bug is distinct from the rollout-era Luna entitlement/terminal-response limitation; fixing passthrough fidelity must not introduce Luna-specific timeout or header behavior.

## Goals / Non-Goals

**Goals:**

- Make all three canonical GPT-5.6 variants usable before and after registry refresh.
- Preserve the official unsuffixed alias and canonicalize it before authorization, routing, reservation, pricing, and upstream forwarding.
- Mirror current Codex-native capability metadata, including Fast, original image detail, `max`, and variant-specific `ultra`/multi-agent metadata.
- Accept explicit Platform prompt-cache controls while removing them at the subscription-upstream boundary so valid client payloads cannot trigger upstream errors or hangs.
- Parse and price cache writes separately from ordinary input and cached reads.
- Expose wire-level `max` in dashboard policy and automation surfaces.
- Preserve native Codex Responses Lite payload fidelity and per-transport lite signaling while keeping non-lite instruction lifting and non-native header stripping intact.
- Prove behavior at the public HTTP/WS routes as well as unit boundaries.

**Non-Goals:**

- Changing the Mac mini deployment topology, credentials, or persistent-data layout.
- Claiming the Platform 1,050,000-token input window through the ChatGPT/Codex backend.
- Reimplementing Codex's client-side `ultra` multi-agent orchestration inside the proxy.
- Adding a new database column solely for cache-write token counts; correct total cost is the required persisted contract.
- Performing a live OpenAI Platform request, which requires separate preview access and credentials.

## Decisions

### Mirror canonical Codex models and derive one official alias

The bootstrap registry will contain only `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`, with raw compatibility fields copied from the current open-source Codex catalog. A single alias mapping will resolve `gpt-5.6` to Sol in both request policy and registry behavior lookups. The alias is derived behavior rather than a synthetic native catalog entry, so a refreshed upstream snapshot remains authoritative and Codex clients continue to see the canonical model set.

Alternative considered: insert `gpt-5.6` as a fourth bootstrap model. This would make the native catalog diverge from Codex's catalog and complicate snapshot authority and plan filtering.

### Keep Codex input-budget reporting separate from Platform pricing limits

`/backend-api/codex/models` and `/v1/models` will report the 372,000 backend input/context budget supplied by the Codex catalog. `/v1/models` will add the known 128,000 max-output metadata. The pricing engine will independently apply published long-context rates when total input is greater than 272,000 tokens.

Alternative considered: publish 1,050,000 as `/v1/models.metadata.context_window`. This would advertise an input budget that the proxied backend catalog does not grant and violates the existing catalog contract.

### Treat `ultra` as Codex-native metadata and `max` as the proxy wire effort

The native catalog will advertise Sol/Terra `ultra` with `multi_agent_version=v2`, while Luna stops at `max` with `v1`. Generic dashboard, API-key, and automation policy controls will support `max` but will not send literal `ultra`; Codex clients consume the native metadata, enable their local delegation behavior, and send `max` on the wire. No global `ultra -> max` rewrite will be added because that would silently discard the client-side delegation semantics.

Alternative considered: accept and rewrite `ultra` everywhere. This would make a request look accepted while omitting the behavior that distinguishes Ultra.

### Preserve native Responses Lite wire fidelity with body-first authority

PR #1158 established the initial passthrough and hardening baseline. The selected PR #1161 slice makes normalized body shape the final authority: once request normalization yields an `input` array containing `type: "additional_tools"`, the whole request is Lite. That same body-derived decision also keeps instruction lifting bypassed and the `input` array unmodified, preserving the tool bundle, developer/system `message` items, `custom_tool_call`, and `custom_tool_call_output`, while leaving top-level `instructions` unchanged. Non-lite requests keep the current instruction-lifting behavior, and typed non-`message` system/developer items still stay out of lifted instruction text as defense in depth.

Inbound internal Lite headers and websocket Lite metadata are transport artifacts, not authority. The proxy strips them on ingress, then re-synthesizes only the canonical transport-specific signal from the body-derived Lite flag: HTTP and compact use `x-openai-internal-codex-responses-lite: true`, websocket `response.create` uses `client_metadata.ws_request_header_x_openai_internal_codex_responses_lite = "true"`, and non-lite requests strip stale markers. This split keeps ordinary HTTP payloads free of the Lite metadata key, preserves compact's existing omission of all `client_metadata`, and lets websocket incremental frames reuse the marker only after an upstream `response.created` accepted the same effective model after alias normalization and API-key enforcement. The HTTP bridge must carry that derived Lite flag through fallback, trim, and retry, and compact trimming must preserve the leading `additional_tools` item plus its adjacent developer message so the Lite prefix survives shrinking.

Alternative considered: continue treating native identity headers or carried metadata as the authority for Lite. This was rejected because copied or stale markers can survive without tools, diverge HTTP from websocket behavior, and fail across compact trimming or HTTP fallback. A Luna-specific workaround was also rejected because the confirmed gap in PR #1161 is transport parity, while Luna rollout limitations remain a separate upstream availability concern.

### Normalize Platform explicit caching at the subscription boundary

Top-level `prompt_cache_options` is accepted by the extra-allow request models, and Chat content coercion explicitly recognizes and validates a `prompt_cache_breakpoint` while dropping unrelated Chat-only keys. A real Mac mini smoke showed that the ChatGPT/Codex subscription backend rejects `prompt_cache_options` and fails to terminate requests containing a content-block breakpoint. The final Responses serializer therefore removes both Platform-only controls before any HTTP or WebSocket upstream path. Supported `prompt_cache_key` affinity remains unchanged. Usage details still type `cache_write_tokens` so HTTP, SSE, WebSocket, compact, warmup, automation, and Chat response mappings can retain it for settlement.

Instruction-role content still requires existing system/developer lifting into the upstream `instructions` string. User content is translated semantically first so validation remains consistent, then all explicit breakpoint markers are removed together at the shared subscription-upstream serializer. This keeps Chat and direct Responses behavior aligned across HTTP and WebSocket transports.

Alternative considered: preserve the Platform fields unchanged. Live subscription-upstream evidence showed an immediate 400 for `prompt_cache_options` and a non-terminating request for `prompt_cache_breakpoint`, so forwarding them would make otherwise valid GPT-5.6 requests unusable. Rejecting the public request was also considered, but accepting and degrading to the backend's automatic cache behavior matches codex-lb's existing treatment of unsupported cache-retention hints.

### Price mutually exclusive input token buckets

Usage normalization will divide total input into cached reads, cache writes, and remaining ordinary input. It will clamp malformed details so the buckets never exceed total input. For GPT-5.6, cache writes use 1.25 times the selected uncached-input rate; cached reads use the cached-input rate; ordinary input and output use their selected rates. When the request exceeds 272,000 input tokens, the long-context rates apply to the full request before the cache-write multiplier. Priority processing is only defined for short context, so an anomalous completed long-context record with a Priority marker uses published Standard long-context rates rather than extrapolated Priority rates. The public cost-breakdown shape remains stable by including cache-write dollars in `inputUsd`.

Alternative considered: count cache-write tokens inside ordinary input and add a 25% surcharge. Explicit buckets are easier to audit and avoid double charging when cached-read and cache-write details coexist.

### Verify public behavior before and after a controlled deployment

Tests cover registry helpers, request policy, price calculations, request coercion, API schemas, and React controls, plus public model-list and Responses/Chat route paths. The Mac mini rollout remains operationally separate from implementation: build a uniquely tagged image, run it in parallel with copied persistent data, cut over only after readiness succeeds, and then verify the live model catalog and real GPT-5.6 traffic. Direct OpenAI Platform credentials are not required because the production path uses the existing Codex/ChatGPT subscription proxy.

## Risks / Trade-offs

- [Upstream preview metadata changes] -> Keep refreshed snapshots authoritative and isolate versioned bootstrap facts in focused tests.
- [Cache usage details are malformed or overlap] -> Clamp cached-read first and cache-write second to the remaining total input, then test overlap cases.
- [Native Ultra is mistaken for a wire value] -> Keep it in Codex-native metadata only and filter it from server-driven policy selectors.
- [Platform and subscription cache-control contracts differ] -> Accept and validate the Platform shape, strip it only at the shared upstream serializer, retain `prompt_cache_key`, and prove behavior with both route tests and a real Mac mini smoke.

## Migration Plan

1. Merge code and OpenSpec changes after unit, integration, frontend, and strict OpenSpec validation pass.
2. Build and smoke the image on an alternate Mac mini port with a copied data volume while the live service remains untouched.
3. After explicit user authorization and a green smoke, back up compose/data, switch the live image tag, and verify readiness, catalogs, real GPT-5.6 traffic, and recorded usage.
4. Roll back by reverting the change; there is no database migration or irreversible data transformation.

## Open Questions

No code migration is required. Mac mini cutover remains gated on successful parallel smoke and a preserved rollback image/compose/data backup.
