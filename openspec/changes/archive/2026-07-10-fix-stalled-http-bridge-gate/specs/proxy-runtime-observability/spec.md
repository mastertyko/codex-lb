## MODIFIED Requirements

### Requirement: Stale pending HTTP bridge retirement is logged

When the service retires an HTTP bridge session because pending precreated replay cannot make progress after upstream close or timeout, or because a pending pre-`response.created` gate holder has made no upstream progress for the configured interval, the service MUST emit a `retire_stale_pending` bridge event with low-cardinality bridge metadata and the terminal detail code. Inactivity-triggered gate retirement MUST also emit existing structured stuck-retirement telemetry. Logs and metrics MUST NOT expose raw bridge keys, request payloads, API keys, or prompt content.

#### Scenario: Failed precreated replay emits retirement event

- **WHEN** precreated HTTP bridge replay fails after upstream close or timeout
- **THEN** the console log includes a HTTP bridge event with `event=retire_stale_pending`
- **AND** the event includes only hashed bridge identity and low-cardinality metadata

#### Scenario: Inactive gate holder triggers retirement telemetry

- **WHEN** a visible gate waiter detects a pending holder whose upstream progress is stale
- **THEN** the service records the stuck-gate retirement reason
- **AND** bridge retirement emits `event=retire_stale_pending`
- **AND** the event includes only hashed bridge identity and low-cardinality metadata
