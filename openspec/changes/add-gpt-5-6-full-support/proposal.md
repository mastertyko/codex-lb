## Why

OpenAI has introduced the GPT-5.6 Sol, Terra, and Luna model family, but codex-lb does not yet provide a complete local contract for the models before an upstream catalog refresh and does not price every GPT-5.6 usage shape correctly. Full compatibility is needed now so Codex and OpenAI-compatible clients receive the official model capabilities, aliases, reasoning controls, safe prompt-cache compatibility, and cost accounting without depending on stale generic GPT-5 fallbacks.

The active GPT-5.6 change also needs to absorb confirmed issue #1157, fixed upstream by PR #1158: truthful native Codex Responses Lite requests can lose their `additional_tools` bundle or lite transport signal before upstream forwarding, which removes shell/filesystem tools even when GPT-5.6 metadata is otherwise correct.

## What Changes

- Add bootstrap catalog entries for `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna` with the Codex-native metadata required by current clients, while preserving refreshed upstream catalog authority.
- Treat `gpt-5.6` as the public alias for `gpt-5.6-sol`, advertise the family through all model-list surfaces, and route it with the same upstream WebSocket preference as the canonical GPT-5.6 models.
- Support the complete GPT-5.6 reasoning contract, including `max` on all three models and `ultra` only where the upstream catalog advertises it.
- Add official standard and long-context GPT-5.6 pricing, including cached reads and cache writes, and use the published long-context threshold for request accounting.
- Accept Platform explicit-cache controls without forwarding fields that the ChatGPT/Codex subscription backend rejects, while preserving supported `prompt_cache_key` affinity and cache-write usage accounting.
- Preserve native Codex Responses Lite payload fidelity by bypassing instruction lifting when an array-shaped `input` contains `type: "additional_tools"`, while leaving non-lite instruction lifting unchanged.
- Forward the Responses Lite signal only for native Codex requests, reconstructing it as `x-openai-internal-codex-responses-lite: true` on upstream HTTP/compact requests and as `ws_request_header_x_openai_internal_codex_responses_lite` in upstream WebSocket `client_metadata`, while still stripping the header for non-native clients.
- Treat this wire-level passthrough contract as distinct from the separately observed Luna entitlement/terminal-response limitation in rollout verification.
- Extend API-key validation and dashboard controls so model-specific reasoning policies can select the new supported effort levels.
- Add route-level regression coverage for catalog responses, aliases, native/non-native HTTP/compact/WebSocket Responses forwarding, Chat Completions translation, and cost accounting.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `model-catalog-compat`: Define GPT-5.6 bootstrap metadata, public aliasing, output limits, and refreshed-snapshot precedence.
- `responses-api-compat`: Define canonical GPT-5.6 routing, reasoning levels, WebSocket preference, native Responses Lite passthrough/signaling, subscription-safe prompt-cache sanitation, and cache-write usage handling.
- `chat-completions-compat`: Define validation and subscription-safe removal of Platform-only cache controls while mapping Chat Completions requests to Responses.
- `api-keys`: Define GPT-5.6 standard/long-context/cache pricing and supported reasoning-policy values in the API and dashboard.
- `frontend-architecture`: Define how dashboard model-policy and automation selectors expose the GPT-5.6 wire-level `max` effort without treating Codex-native `ultra` as an upstream effort.

## Impact

The change affects the model registry and model-list endpoints, Responses request policy and transport selection, Chat Completions coercion, usage parsing and pricing, API-key and automation schemas/services, dashboard model controls, and their backend/frontend test suites. Deployment was initially deferred; after explicit user authorization, the verified build will be rolled out to the existing Mac mini compose service without changing its infrastructure topology.
