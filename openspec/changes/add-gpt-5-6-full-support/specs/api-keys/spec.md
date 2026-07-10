## ADDED Requirements

### Requirement: GPT-5.6 pricing and aliasing are recognized

The system MUST price `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna` using their published standard, Flex, and Priority rates, and MUST resolve `gpt-5.6` to the Sol price entry. Sol MUST use $5 input, $0.50 cached input, and $30 output per million standard tokens; Terra MUST use $2.50, $0.25, and $15; Luna MUST use $1, $0.10, and $6. When total input tokens are greater than 272,000, the full standard or Flex request MUST use 2x input, 2x cached-input, and 1.5x output rates. Flex MUST use 0.5x standard rates. Priority short-context requests MUST use 2x standard input, cached-input, and output rates. Because OpenAI does not support Priority processing for long-context requests, terminal usage above 272,000 input tokens MUST fall back to published Standard long-context pricing rather than applying an unpublished Priority long-context tariff.

#### Scenario: Each canonical GPT-5.6 model uses its standard price

- **WHEN** a standard-tier request at or below 272,000 input tokens completes for Sol, Terra, or Luna
- **THEN** cost accounting uses that variant's published standard rates

#### Scenario: Unsuffixed GPT-5.6 uses Sol pricing

- **WHEN** a request completes with model `gpt-5.6`
- **THEN** cost accounting uses the same rates as `gpt-5.6-sol`

#### Scenario: GPT-5.6 long-context threshold is exclusive

- **WHEN** a GPT-5.6 request completes with exactly 272,000 input tokens
- **THEN** standard rates apply
- **WHEN** it completes with 272,001 input tokens
- **THEN** long-context rates apply to the full request

#### Scenario: GPT-5.6 Flex request uses published discounted rates

- **WHEN** a GPT-5.6 request completes with billable `service_tier: "flex"`
- **THEN** cost accounting uses the published Flex rate for its context length

#### Scenario: GPT-5.6 Priority request uses published short-context rates

- **WHEN** a GPT-5.6 request at or below 272,000 input tokens completes with billable `service_tier: "priority"`
- **THEN** cost accounting uses the published Priority rates

#### Scenario: Long-context usage never invents Priority pricing

- **WHEN** terminal usage exceeds 272,000 input tokens despite a Priority tier marker
- **THEN** cost accounting uses the published Standard long-context rates
- **AND** it does not extrapolate the short-context Priority table

### Requirement: GPT-5.6 cache writes are priced separately

For GPT-5.6 usage, `cached_tokens`, `cache_write_tokens`, and remaining ordinary input tokens MUST be mutually exclusive cost buckets. Cache writes MUST cost 1.25 times the applicable uncached-input rate, including when long-context rates apply. If usage details overlap or exceed total input, normalization MUST clamp the buckets so no input token is billed more than once. Existing cost breakdown responses MUST include cache-write dollars in `inputUsd` without changing their schema.

#### Scenario: Mixed read, write, and ordinary input is not double charged

- **WHEN** a GPT-5.6 usage record contains ordinary input, cached reads, and cache writes
- **THEN** each token is assigned to at most one bucket
- **AND** the total cost uses the ordinary, cached-read, and 1.25x cache-write rates respectively

#### Scenario: Long-context cache write uses long-context input rate

- **WHEN** a GPT-5.6 request above 272,000 input tokens reports cache writes
- **THEN** each cache-write token costs 1.25 times the long-context uncached-input rate

#### Scenario: Malformed usage buckets are clamped

- **WHEN** cached-read plus cache-write details exceed total input tokens
- **THEN** normalized billable input remains equal to total input tokens
- **AND** cost accounting does not double charge the overlap

### Requirement: API-key reasoning enforcement supports max wire effort

API-key create, update, response, and dashboard schemas MUST accept and preserve `max` as an enforced reasoning effort. The API-key policy surface MUST NOT advertise `ultra` as a wire effort because Codex implements Ultra's multi-agent behavior client-side. Existing stored values outside the current supported set MUST continue to be handled leniently on read according to the existing compatibility contract.

#### Scenario: Create API key enforcing max

- **WHEN** an operator creates an API key with `enforcedReasoningEffort: "max"`
- **THEN** the backend persists and returns `max`
- **AND** a request using the key forwards `reasoning.effort: "max"`

#### Scenario: Dashboard offers max but not ultra as API-key policy

- **WHEN** an operator opens an API-key create or edit dialog
- **THEN** the reasoning-effort selector includes `max`
- **AND** it does not include `ultra`
