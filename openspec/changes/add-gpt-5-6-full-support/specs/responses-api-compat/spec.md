## MODIFIED Requirements

### Requirement: Responses Lite transport markers are derived from normalized input

The service MUST determine full-request Responses Lite enablement from the normalized request body alone. A request whose normalized `input` array contains any item with `type = "additional_tools"` MUST be treated as Lite for the full request. `X-OpenAI-Internal-Codex-Responses-Lite` and `ws_request_header_x_openai_internal_codex_responses_lite` MUST be treated as derived transport markers, MUST be stripped from inbound request state regardless of client identity, and MUST NOT by themselves enable Lite forwarding. For upstream HTTP attempts, including compact requests and HTTP bridge retries, a Lite request MUST synthesize `x-openai-internal-codex-responses-lite: true`, while a non-Lite request MUST omit that header. Ordinary upstream HTTP payloads MUST omit the Lite metadata key while preserving unrelated `client_metadata`. Compact payloads MUST continue to omit all `client_metadata`; compact trimming MUST preserve the leading Lite prefix consisting of the `additional_tools` item and its adjacent developer message so body-derived Lite detection survives trimming. Upstream websocket `response.create` frames MUST carry Lite only through `client_metadata.ws_request_header_x_openai_internal_codex_responses_lite = "true"`; non-Lite websocket frames MUST omit that key while preserving unrelated metadata. When websocket flow falls back to HTTP, the derived Lite state MUST survive fallback, trim, and retry without reusing stale inbound markers. A marker-only websocket frame that omits `additional_tools` MAY reuse the canonical Lite metadata only after the same connection has observed an upstream `response.created` that accepted the same effective model after alias normalization and API-key enforcement; prewarm traffic, non-accepted requests, later model changes, or API-key changes MUST NOT establish or reuse that continuity.

#### Scenario: Body-only HTTP request synthesizes the Lite header

- **WHEN** a Responses request normalizes to an `input` array containing `{"type":"additional_tools", ...}` and carries no inbound Lite header
- **THEN** the upstream HTTP headers include `x-openai-internal-codex-responses-lite: true`
- **AND** the upstream HTTP payload omits the Lite metadata key

#### Scenario: Stale inbound Lite header without tools is stripped

- **WHEN** a request has `X-OpenAI-Internal-Codex-Responses-Lite: TRUE` but its normalized `input` contains no `additional_tools` item
- **THEN** the upstream HTTP headers omit `x-openai-internal-codex-responses-lite`
- **AND** the upstream HTTP payload and websocket payload both omit the Lite metadata key

#### Scenario: HTTP and websocket Lite signaling split by transport

- **WHEN** the same Lite-shaped request is forwarded once over HTTP and once over upstream websocket
- **THEN** the upstream HTTP attempt carries Lite only through `x-openai-internal-codex-responses-lite: true`
- **AND** the upstream websocket `response.create.client_metadata` carries `ws_request_header_x_openai_internal_codex_responses_lite: "true"`

#### Scenario: Websocket Lite fallback to HTTP preserves the derived signal

- **WHEN** a Lite-shaped websocket request falls back to an upstream HTTP attempt
- **THEN** the fallback HTTP headers include `x-openai-internal-codex-responses-lite: true`
- **AND** the fallback HTTP payload omits the Lite metadata key

#### Scenario: Oversized compact trimming preserves the Lite prefix

- **WHEN** a compact request is Lite-shaped and must trim an oversized `input`
- **THEN** the trimmed request still begins with the `additional_tools` item followed by its adjacent developer message
- **AND** the upstream compact HTTP headers include `x-openai-internal-codex-responses-lite: true`

#### Scenario: HTTP bridge retry keeps body-derived Lite after prefix trimming

- **WHEN** a Lite-shaped HTTP request is retried or trimmed by the HTTP bridge
- **THEN** every upstream HTTP attempt includes `x-openai-internal-codex-responses-lite: true`
- **AND** no attempt reuses an inbound Lite header or payload marker as the source of truth

#### Scenario: Same-model incremental websocket frames may reuse the marker after acceptance

- **GIVEN** an upstream `response.created` already accepted a Lite-shaped request for the effective model `gpt-5.6-sol`
- **WHEN** the same connection sends a later marker-only incremental websocket frame for the same effective model
- **THEN** the upstream websocket frame includes `ws_request_header_x_openai_internal_codex_responses_lite: "true"`

#### Scenario: Accepted websocket Lite trust does not cross connections

- **GIVEN** one websocket connection received `response.created` for a Lite-shaped request
- **WHEN** a different connection with the same session and API-key identity sends a marker-only frame for the same effective model
- **THEN** the upstream websocket frame omits `ws_request_header_x_openai_internal_codex_responses_lite`

#### Scenario: Model or API-key changes clear websocket Lite continuity

- **GIVEN** an upstream `response.created` already accepted a Lite-shaped request
- **WHEN** a later marker-only incremental websocket frame changes the effective model or is reauthorized under a different API key
- **THEN** the upstream websocket frame omits `ws_request_header_x_openai_internal_codex_responses_lite`

#### Scenario: A rejected marker-only request clears established Lite trust

- **GIVEN** the connection previously received `response.created` for a Lite-shaped request
- **WHEN** a later marker-only request is rejected locally or upstream before its own `response.created`
- **THEN** later marker-only websocket frames on that connection omit `ws_request_header_x_openai_internal_codex_responses_lite`
- **AND** a later full Lite-shaped request must re-establish continuity from its own accepted `response.created`

#### Scenario: Queued marker-only requests revalidate trust after gate admission

- **GIVEN** a marker-only websocket request was normalized while an earlier request held the response-create gate
- **WHEN** the earlier request clears or changes Lite trust before the queued request acquires the gate
- **THEN** the queued request revalidates the current connection-local effective model before sending
- **AND** it omits `ws_request_header_x_openai_internal_codex_responses_lite` unless its own body contains `additional_tools`

#### Scenario: Prewarm or non-accepted websocket requests do not establish Lite trust

- **WHEN** a websocket prewarm or non-accepted request sends only the Lite marker without `additional_tools`
- **THEN** later marker-only websocket frames on that connection omit `ws_request_header_x_openai_internal_codex_responses_lite`
- **AND** a later full Lite-shaped request must establish continuity from its own accepted `response.created`

## ADDED Requirements

### Requirement: GPT-5.6 aliases normalize before proxy policy decisions

For Responses proxy traffic, the system MUST treat `gpt-5.6` as an alias of `gpt-5.6-sol`. It MUST canonicalize that alias before API-key model authorization, account-plan and service-tier lookup, usage reservation, transport selection, pricing, and upstream forwarding. Cursor-style supported suffixes on the alias and canonical GPT-5.6 variants MUST continue to normalize to canonical model fields. Unknown suffixes MUST remain unchanged.

#### Scenario: Unsuffixed GPT-5.6 request forwards to Sol

- **WHEN** a client sends a Responses request with `model: "gpt-5.6"`
- **THEN** the forwarded request uses `model: "gpt-5.6-sol"`
- **AND** pricing and routing use the Sol identity

#### Scenario: GPT-5.6 alias and canonical model are allowlist-equivalent

- **WHEN** an API key allowlist contains `gpt-5.6-sol` and the client requests `gpt-5.6`
- **THEN** model access is permitted
- **AND** the inverse canonical request with an alias allowlist is also permitted

#### Scenario: Qualified GPT-5.6 variant preserves max effort

- **WHEN** a client sends `model: "gpt-5.6-terra-max"`
- **THEN** the forwarded request uses `model: "gpt-5.6-terra"`
- **AND** the forwarded request uses `reasoning.effort: "max"`

### Requirement: GPT-5.6 bootstrap routing prefers upstream WebSockets

Before registry refresh, transport preference and plan filtering MUST recognize all canonical GPT-5.6 variants and the official Sol alias. A refreshed snapshot MUST remain authoritative for those lookups.

#### Scenario: Auto transport recognizes GPT-5.6 before warmup

- **GIVEN** the model registry has no refreshed upstream snapshot
- **WHEN** auto transport selection receives a streaming request for `gpt-5.6`, Sol, Terra, or Luna without an HTTP-forcing tool
- **THEN** it selects the upstream WebSocket transport

#### Scenario: Snapshot can override GPT-5.6 bootstrap preference

- **GIVEN** a refreshed snapshot marks a GPT-5.6 variant as not WebSocket-preferred
- **WHEN** model preference is queried for that variant
- **THEN** the refreshed preference is returned

### Requirement: Responses Lite input payloads pass through unmodified

When an array-shaped Responses `input` contains an item with `type = "additional_tools"`, the service MUST treat the request as Responses Lite shaped and MUST forward the `input` array unmodified to upstream HTTP and websocket transports. In particular the service MUST preserve the `additional_tools` tool bundle, developer/system `message` items (which MUST NOT be lifted into top-level `instructions`), `custom_tool_call` items, and `custom_tool_call_output` items, and MUST leave top-level `instructions` unchanged. Instruction lifting for non-lite requests MUST also skip any `system`/`developer` input item whose `type` is present and is not `"message"`.

#### Scenario: additional_tools bundle reaches upstream intact

- **WHEN** a Codex client sends a Responses request whose `input` starts with `{"type": "additional_tools", "role": "developer", "tools": [...]}` followed by a developer instructions message and user content
- **THEN** the upstream request's `input` equals the inbound `input`
- **AND** top-level `instructions` keeps its inbound value

#### Scenario: Lite custom tool call items survive forwarding

- **WHEN** a lite-shaped Responses request includes `custom_tool_call` and `custom_tool_call_output` input items
- **THEN** those items reach upstream unmodified over both the HTTP route and the websocket bridge

#### Scenario: Non-lite instruction lifting is unaffected

- **WHEN** a request without an `additional_tools` item carries system or developer messages in `input`
- **THEN** their text is still lifted into top-level `instructions`
- **AND** `custom_tool_call_output` items in the same `input` are preserved

### Requirement: GPT-5.6 Platform cache controls are safe on the subscription backend

The OpenAI-compatible Responses path MUST accept a valid top-level `prompt_cache_options` object and `prompt_cache_breakpoint: {"mode":"explicit"}` on supported input content blocks, but MUST remove both Platform-only controls before forwarding to the ChatGPT/Codex subscription backend. The supported `prompt_cache_key` field MUST remain intact. Existing sanitation of interleaved reasoning and unsupported request fields MUST continue to apply, and the proxy MUST NOT invent cache breakpoints.

#### Scenario: Direct Responses cache controls degrade safely

- **WHEN** a `/v1/responses` request for a GPT-5.6 model contains a supported input content block with an explicit cache breakpoint and `prompt_cache_options: {"mode":"explicit","ttl":"30m"}`
- **AND** it contains a supported `prompt_cache_key`
- **THEN** the subscription-upstream payload omits `prompt_cache_options` and every content-block `prompt_cache_breakpoint`
- **AND** it preserves `prompt_cache_key`

#### Scenario: Same-named Lite tool-schema properties remain intact

- **WHEN** a Lite `additional_tools` definition contains a custom schema property named `prompt_cache_breakpoint`
- **THEN** that schema property reaches the subscription upstream unchanged because it is not a Platform content-block cache control

#### Scenario: Existing interleaved-reasoning sanitation remains active

- **WHEN** a content block contains a valid cache breakpoint and a locally stripped interleaved-reasoning key
- **THEN** existing normalization continues to omit the interleaved-reasoning key
- **AND** the final subscription-upstream payload also omits the breakpoint

### Requirement: GPT-5.6 cache-write usage reaches cost settlement

When a Responses HTTP, SSE, or WebSocket terminal payload reports `usage.input_tokens_details.cache_write_tokens`, the system MUST retain that value as a typed usage detail until request-cost and API-key usage settlement completes. Chat-compatible usage translation MUST also preserve the value as `prompt_tokens_details.cache_write_tokens`.

#### Scenario: WebSocket terminal usage retains cache writes

- **WHEN** an upstream WebSocket `response.completed` event reports non-zero `cache_write_tokens`
- **THEN** the request's finalized cost includes the cache-write rate

#### Scenario: HTTP Responses usage retains cache writes

- **WHEN** an upstream HTTP Responses body reports non-zero `cache_write_tokens`
- **THEN** the request's finalized cost includes the cache-write rate

#### Scenario: Responses-to-Chat usage mapping retains cache writes

- **WHEN** a Chat Completions request is fulfilled through Responses and usage reports cache writes
- **THEN** the Chat completion usage contains `prompt_tokens_details.cache_write_tokens`
