## ADDED Requirements

### Requirement: Supported account probe request
The account probe SHALL use the supported Codex Responses request contract without unsupported output-limit parameters, while retaining bounded network timeouts.

#### Scenario: Upstream rejects output-limit parameters
- **WHEN** the probe calls an upstream that rejects max_output_tokens
- **THEN** its request SHALL omit that parameter and report the resulting upstream status
