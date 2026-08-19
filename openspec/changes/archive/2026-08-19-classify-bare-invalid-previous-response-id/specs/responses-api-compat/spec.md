## MODIFIED Requirements

### Requirement: Codex WebSocket stale-anchor failures remain recoverable by a full-context retry
When serving or consuming the Codex-native `/backend-api/codex/responses` WebSocket route, upstream `previous_response_id` MUST be treated as an ephemeral optimization rather than durable conversation state. A stale-anchor continuity failure during a long-wait tool-output continuation MUST NOT hard-end the user turn while recoverable full history still exists at codex-lb or the client. The service MUST classify structured `previous_response_not_found` errors and precise invalid-anchor or previous-response-not-found messages as stale-anchor continuity loss even when upstream omits optional `code` or `param` fields. The sanitized signal the service surfaces for a Codex-native stale-anchor failure MUST be the canonical `previous_response_not_found` error code, because that is the code compatible clients act on to clear their continuation cache and resend full context. The service MUST NOT expose the raw upstream error envelope or the missing upstream response id.

#### Scenario: Bare invalid previous-response message triggers safe replay
- **GIVEN** a Codex-native WebSocket follow-up contains complete replayable conversation input
- **AND** codex-lb injects a prior `previous_response_id` continuity anchor
- **WHEN** upstream responds with no `code`, no `param`, an optional `type = "invalid_request_error"`, and message `Invalid \`previous_response_id\`.`
- **THEN** codex-lb classifies the failure as stale-anchor continuity loss
- **AND** retries the self-contained request once without `previous_response_id`
- **AND** does not expose the raw upstream error downstream

#### Scenario: Client-owned delta receives canonical recovery signal
- **GIVEN** a Codex-native follow-up contains only input that depends on its client-supplied `previous_response_id`
- **WHEN** upstream rejects that anchor with a precise stale-anchor message and omits structured `code` or `param` fields
- **THEN** codex-lb MUST NOT replay the dependent delta without its anchor
- **AND** MUST return the canonical `previous_response_not_found` classifier without the response id
- **AND** a compatible client MAY clear its continuation cache and resend retained full context

#### Scenario: Unrelated invalid requests remain generic
- **WHEN** upstream responds with an unrelated invalid-request type, parameter, or message
- **THEN** codex-lb MUST NOT classify it as stale-anchor continuity loss
- **AND** MUST NOT trigger a full-context stale-anchor retry

### Requirement: Cross-account replay requires account-neutral payload proof
The service MUST distinguish a request that is safe to resend on the same account from a request that is safe to move to another account. Before any replay, retry, or transport fallback sends an exact Responses payload to a different account, that outgoing payload MUST pass the canonical account-neutral fresh-replay predicate. Removing `previous_response_id` MUST NOT remove the required-owner constraint for a payload that contains encrypted reasoning, server-assigned ids, files, hosted state, account-local references, unknown fields, or any other account-bound state.

#### Scenario: Account-bound stale replay remains owner-pinned
- **GIVEN** a self-contained full resend contains encrypted reasoning or another account-bound field
- **AND** the request's stale anchor is removed for one bounded replay
- **WHEN** the original account is unavailable
- **THEN** codex-lb MUST NOT send the replay body to another account
- **AND** MUST fail with a sanitized required-owner continuity error

#### Scenario: Account-neutral stale replay may move
- **GIVEN** the exact anchor-free replay body passes the canonical account-neutral predicate
- **WHEN** the preferred account is unavailable before visible output
- **THEN** codex-lb MAY select another eligible account
- **AND** MUST still enforce API-key assignment and security-work authorization constraints

#### Scenario: Cross-transport fallback uses the same portability proof
- **WHEN** an HTTP Responses request is considered for WebSocket fallback on another account
- **THEN** codex-lb MUST apply the canonical account-neutral predicate to the exact fallback payload
- **AND** MUST fail closed rather than forwarding account-bound state
