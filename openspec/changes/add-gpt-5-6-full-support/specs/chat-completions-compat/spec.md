## MODIFIED Requirements

### Requirement: Map chat requests to Responses wire format

The service MUST map chat messages into the Responses request format by merging `system`/`developer` text content into `instructions` and forwarding all other messages as `input`. This instruction lift MUST also apply when `response_format.type` is `json_object`, because the proxied Responses backend rejects `system` and `developer` roles in `input`. Tool definitions MUST be normalized to the Responses tool schema, and `tool_choice`, `reasoning_effort`, and `response_format` MUST be mapped consistently. Valid `prompt_cache_options` and supported content-block `prompt_cache_breakpoint` values MUST be recognized during translation but removed before subscription-upstream forwarding; supported `prompt_cache_key` MUST remain intact. Unrelated Chat-only content fields MUST NOT leak upstream.

#### Scenario: System message normalization

- **WHEN** the client sends a `system` message followed by a `user` message
- **AND** the request does not use `response_format.type = "json_object"`
- **THEN** the service maps the system content to `instructions` and the user message to `input`

#### Scenario: JSON object response format keeps instruction text in instructions

- **WHEN** the client sends `response_format: {"type":"json_object"}` with a `system` or `developer` message that instructs JSON output
- **THEN** the mapped Responses payload merges that message text into `instructions`
- **AND** it does not forward a `system` or `developer` role in `input`

#### Scenario: Tool choice values

- **WHEN** the client sets `tool_choice` to `none`, `auto`, or `required`
- **THEN** the service forwards the value consistently in the mapped Responses request

#### Scenario: Explicit prompt-cache controls are recognized then removed

- **WHEN** a GPT-5.6 Chat Completions request attaches `prompt_cache_breakpoint: {"mode":"explicit"}` to a supported content block that can be translated without changing its role semantics
- **AND** it includes request-wide `prompt_cache_options` and a `prompt_cache_key`
- **THEN** content coercion validates the marker while preserving the translated text, image, or file semantics
- **AND** the final subscription-upstream payload omits both Platform-only controls
- **AND** it preserves `prompt_cache_key`

#### Scenario: Cache-control recognition does not retain arbitrary keys

- **WHEN** the same Chat content block also contains an unrelated client-only field
- **THEN** the mapped content retains neither the unrelated field nor the breakpoint at the upstream boundary
