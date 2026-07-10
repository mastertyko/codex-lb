# GPT-5.6 support context

## External contracts

- OpenAI model pages define `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`; the unsuffixed `gpt-5.6` alias routes to Sol. The Platform context window is 1,050,000 and max output is 128,000.
- Prompts with more than 272,000 input tokens use 2x input and 1.5x output pricing for the full request.
- Standard prices per million tokens are:
  - Sol: $5 input, $0.50 cached read, $30 output.
  - Terra: $2.50 input, $0.25 cached read, $15 output.
  - Luna: $1 input, $0.10 cached read, $6 output.
- Flex processing uses 0.5x the published standard GPT-5.6 token rates for both short and long context. Priority processing publishes short-context rates at 2x standard for all three variants; OpenAI's Priority guide says long context is not supported. If completed terminal usage nevertheless crosses 272,000 tokens with a Priority marker, accounting falls back to published Standard long-context rates instead of inventing a Priority-long tariff.
- GPT-5.6 cache writes are reported as `cache_write_tokens` and cost 1.25x the applicable uncached-input rate. OpenAI Platform documents explicit `prompt_cache_breakpoint` and `prompt_cache_options` controls, but the proxied ChatGPT/Codex subscription backend does not accept them. codex-lb accepts the client shape, strips both controls before subscription forwarding, retains supported `prompt_cache_key` affinity, and still accounts for any upstream-reported cache writes.
- The current Codex open-source catalog uses a 372,000-token backend budget and minimum client `0.144.0` for all three models. Sol/Terra advertise efforts through `ultra` with multi-agent v2; Luna advertises through `max` with v1.
- Issue #1157, upstream PR #1158, and PR #1161 head `1eb47a80f71b8f906bfc2bd3a54dacf8f2b2c38a` show that truthful GPT-5.6 Responses Lite is identified by a normalized `input` item with `type: "additional_tools"`. HTTP and compact derive `x-openai-internal-codex-responses-lite: true` from that body shape, websocket `response.create` uses canonical `ws_request_header_x_openai_internal_codex_responses_lite` metadata, and copied inbound Lite markers are never authoritative.

## Sources

- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/api/docs/models/gpt-5.6-terra
- https://developers.openai.com/api/docs/models/gpt-5.6-luna
- https://developers.openai.com/api/docs/guides/prompt-caching
- https://developers.openai.com/api/docs/guides/latest-model
- https://github.com/openai/codex/commit/3380969a29134630d56feb6218e8e8dcc5e8196d
- https://github.com/Soju06/codex-lb/issues/1157
- https://github.com/Soju06/codex-lb/pull/1158
- https://github.com/Soju06/codex-lb/commit/1eb47a80f71b8f906bfc2bd3a54dacf8f2b2c38a

## Operational boundary

Mac mini deployment was initially held. The user subsequently authorized rollout, so the implementation is deployed only after local gates and a parallel server smoke, with the prior image, compose file, and persistent data retained as rollback anchors.

## Platform-to-subscription cache-control boundary

codex-lb intentionally lifts Chat `system` and `developer` text into the Responses `instructions` field because the proxied backend rejects those roles in `input`. The adapter first recognizes valid explicit breakpoints on semantics-preserving user translations (`text`, `image_url`, and `file`) and continues to reject unsupported Chat audio. At the final shared serializer, `prompt_cache_options` and every nested `prompt_cache_breakpoint` are removed for both direct Responses and translated Chat traffic. This is required by live subscription-backend behavior observed during the parallel Mac mini smoke on 2026-07-09: the options object returned `Unsupported parameter`, while the content marker produced no terminal response. `prompt_cache_key` remains the supported caller-controlled cache-affinity mechanism.

## Native Responses Lite wire contract

Issue #1157 and PR #1158 explain the historical GPT-5.6 Lite passthrough gap, and the selected PR #1161 head slice closes the remaining parity gap by making normalized body shape authoritative. If request normalization leaves any `input` item with `type: "additional_tools"`, codex-lb treats the whole request as Lite, keeps the developer instructions message in `input`, preserves `custom_tool_call` / `custom_tool_call_output`, strips inbound internal Lite markers, and re-synthesizes only the canonical per-transport signal. HTTP and compact emit `x-openai-internal-codex-responses-lite: true`, websocket `response.create` emits `ws_request_header_x_openai_internal_codex_responses_lite: "true"`, non-lite requests strip stale markers, compact trimming must keep the `additional_tools` prefix plus its adjacent developer message, and HTTP bridge trim/retry paths must preserve the derived Lite decision. Marker-only incremental websocket frames are trusted only after upstream `response.created` accepted the same effective model after alias and API-key enforcement; prewarm, rejected, model-switched, or API-key-switched requests do not establish that trust. This remains distinct from the Luna rollout limitation below: account-level model-not-found or missing terminal-response behavior does not change the required Responses Lite transport contract or justify a Luna-specific workaround.

## Live rollout verification (2026-07-09)

- The deployed Mac mini image is `codex-lb:local-gpt56-5c67c2efae8c-20260709T194941Z`; the service remained healthy after cutover and emitted no new error, critical, or traceback log entries during verification.
- The live OpenAI-compatible catalog exposes Sol, Terra, and Luna with a 372,000-token Codex backend context budget and 128,000 max output tokens.
- Real subscription-backend calls succeeded for the `gpt-5.6` alias/Sol over Responses, Terra with `max` through Chat Completions, and Terra with `max` over downstream and upstream WebSocket transport.
- A repeated 6,019-input-token Sol prompt proved automatic cache-read accounting end to end: the second request reported 5,888 cached tokens and persisted the discounted cost. Explicit Platform cache controls were accepted at the public contract and safely stripped before subscription forwarding.
- Luna is implemented and advertised from the current upstream catalog, and copied production logs contain earlier successful Luna WebSocket traffic. During the final rollout smoke, however, every currently configured Pro account returned an upstream model-not-found result or did not produce a terminal response for Luna. This is recorded as a current account rollout/entitlement limitation rather than hidden as a successful live check.
- Rollback anchors preserve the previous image, compose file, encryption key, and a consistent SQLite online backup under `/Users/roland/srv/codex-lb/backups/gpt56-20260709T193536Z/`.
