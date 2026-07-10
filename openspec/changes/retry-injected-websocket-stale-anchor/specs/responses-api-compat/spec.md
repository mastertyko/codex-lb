## ADDED Requirements

### Requirement: Retry-safe stale WebSocket anchors replay before owner fail-closed handling
When a direct Responses WebSocket request has a prepared retry-safe fresh upstream request body without `previous_response_id`, the service MUST use that replay path for upstream `previous_response_not_found` before applying preferred-owner unavailable handling. This applies when the stale anchor was proxy-injected from session continuity as well as when a client full-resend was classified retry-safe.

#### Scenario: proxy-injected stale anchor has a preferred owner
- **GIVEN** a WebSocket request has `previous_response_id`, a preferred owner account, and `fresh_upstream_request_is_retry_safe` with a no-anchor replay body
- **WHEN** upstream emits `previous_response_not_found` before `response.created`
- **THEN** the service reconnects and replays the prepared no-anchor request
- **AND** it does not rewrite the turn to `previous_response_owner_unavailable`

### Requirement: Pre-created previous-response WebSocket EOF retries stay owner-bound
When a direct Responses WebSocket request carries a client-supplied `previous_response_id` and the upstream websocket closes before any `response.*` frame has been observed, the service MUST retry the request at most once on the same owner account. The service MUST NOT exclude or rebind the owner account for this replay. If any `response.*` frame has already been observed before the close, the service MUST fail closed unless the request has a prepared retry-safe fresh body without `previous_response_id`.

#### Scenario: short previous-response continuation closes before response creation
- **GIVEN** a WebSocket request has a client-supplied `previous_response_id`, a preferred owner account, no retry-safe fresh full-context body, and no observed upstream `response.*` frame
- **WHEN** the upstream websocket closes without `response.created` or a terminal event
- **THEN** the service reconnects to the same owner account and replays the request once
- **AND** the owner account is not added to excluded accounts for that replay

#### Scenario: previous-response continuation closes after response creation
- **GIVEN** a WebSocket request has a client-supplied `previous_response_id` and no retry-safe fresh full-context body
- **AND** upstream emitted `response.created`
- **WHEN** the upstream websocket closes before a terminal event
- **THEN** the service emits `stream_incomplete` for the existing response id
- **AND** it does not replay the same `previous_response_id` request
- **AND** the request log records upstream failure metadata identifying that replay was refused after `response.created` without a retry-safe fresh body

### Requirement: Codex WebSocket prewarm completions are classified separately
When a direct Responses WebSocket request carries Codex turn metadata with `request_kind: "prewarm"`, the service MUST preserve that request kind in request logs. Empty-output prewarm completions MUST NOT update account success state or previous-response ownership, while still allowing the upstream terminal frame to pass through.

#### Scenario: empty prewarm completion does not look like user turn progress
- **GIVEN** a direct WebSocket request carries `x-codex-turn-metadata` with `request_kind: "prewarm"`
- **WHEN** upstream emits `response.completed` with zero output tokens
- **THEN** the request log records `request_kind` as `prewarm`
- **AND** the service does not mark the account successful for that completion
- **AND** the service does not remember the response id as a usable previous-response owner

### Requirement: Codex compact requests are bounded by the proxy request budget
When `/backend-api/codex/responses/compact` is called for Codex auto-compaction, the service MUST bound the upstream compact call by the remaining proxy compact request budget even when no explicit upstream compact timeout is configured. The service MUST preserve Codex turn metadata `request_kind` in compact request logs so auto-compaction failures are distinguishable from normal user turns.

#### Scenario: auto-compaction cannot hang past the proxy budget
- **GIVEN** a Codex compact request carries `x-codex-turn-metadata` with `request_kind: "compaction"`
- **AND** no explicit upstream compact timeout is configured
- **WHEN** the service calls upstream
- **THEN** the upstream call receives both connect and total timeout overrides from the remaining compact request budget
- **AND** the request log records `request_kind` as `compaction`
