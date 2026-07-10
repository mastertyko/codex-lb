## ADDED Requirements

### Requirement: Stuck HTTP bridge response-create gate sessions are retired
When a visible HTTP bridge request times out waiting for a per-session response-create gate, the proxy MUST retire the bridge session only if a pending gate holder is still awaiting `response.created`, has not exposed downstream output, and has made no upstream progress for at least the configured stuck-gate retirement threshold. The retirement MUST emit a structured low-cardinality log and a Prometheus counter without raw keys or prompt content.

#### Scenario: Inactive pending work blocks a visible gate waiter
- **WHEN** a visible HTTP bridge request receives `response_create_gate_timeout`
- **AND** at least one pending pre-`response.created` gate holder has made no upstream progress for the configured threshold
- **THEN** the proxy retires the bridge session so later requests can create a fresh session
- **AND** the waiter is rejected cleanly with `response_create_gate_timeout`

#### Scenario: Healthy active request is not retired during a normal wait
- **WHEN** a visible HTTP bridge request times out waiting for the gate
- **AND** each pending gate holder has made upstream progress within the configured threshold or has already exposed downstream output
- **THEN** the proxy rejects only the waiter
- **AND** the bridge session remains available for the existing in-flight request
