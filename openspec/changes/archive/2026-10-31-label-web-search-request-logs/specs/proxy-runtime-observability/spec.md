## ADDED Requirements

### Requirement: Standalone web search is identifiable in request logs

For a standalone `alpha/search` request that reaches Codex control handling, the persisted request log and dashboard request-log API MUST identify the request kind as `codex_control_alpha_search`. When the request is dispatched to the upstream HTTP control client, the log MUST record upstream transport `http`, including when that attempt fails. A request rejected before upstream dispatch MUST leave upstream transport unknown. Model, token, and cost fields MUST NOT be fabricated for these control requests.

#### Scenario: Search succeeds or fails after upstream dispatch
- **WHEN** a standalone search reaches the upstream HTTP control client and succeeds or returns an upstream error
- **THEN** its request-log API entry has `requestKind` equal to `codex_control_alpha_search` and `upstreamTransport` equal to `http`
- **AND** its actual success or error outcome and existing response contract are preserved
- **AND** model and token fields remain empty or null

#### Scenario: Search cannot select an upstream account
- **WHEN** a standalone search reaches control handling but no upstream account is available
- **THEN** its log still identifies the search request kind
- **AND** upstream transport remains unknown

### Requirement: Dashboard labels standalone web search without inferring historical identity

The request table and request details MUST display the localized `Web search` label for `codex_control_alpha_search` entries in place of an empty model label. The request-kind detail MUST use the same label. The table MUST render the recorded upstream HTTP transport through its existing transport display. Rows without that explicit request kind MUST retain their existing model and request-kind presentation even when model and usage fields are empty.

#### Scenario: Operator opens search details
- **WHEN** an operator views a logged standalone search and opens its details
- **THEN** the table and details identify it as `Web search` in the English locale
- **AND** the table displays `Up HTTP` for a dispatched search
- **AND** missing token and cost values remain unavailable

#### Scenario: Legacy or unrelated control row lacks model metadata
- **WHEN** a row has an empty model but is not explicitly classified as `codex_control_alpha_search`
- **THEN** the dashboard does not label it as web search or infer its upstream transport
