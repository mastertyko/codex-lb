## MODIFIED Requirements

### Requirement: Bootstrap model catalog is available before refresh

Before the first successful upstream model-registry refresh, the system MUST
serve a conservative static catalog of known Codex model slugs from both
`GET /v1/models` and `GET /backend-api/codex/models`. This static catalog is a
bundled fallback for startup/offline paths; refreshed upstream model-registry
data remains the authoritative source once available. The bootstrap catalog MUST
include `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.4`,
`gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `gpt-5.2`, and
`codex-auto-review`, and MUST NOT invent unverified variant slugs such as
`gpt-5.5-pro` or a synthetic native `gpt-5.6` entry.

#### Scenario: OpenAI-compatible models endpoint serves bootstrap slugs

- **GIVEN** the model registry has no refreshed upstream snapshot
- **WHEN** a client calls `GET /v1/models`
- **THEN** the response contains exactly the bootstrap model slugs
- **AND** the response includes all three canonical GPT-5.6 variants
- **AND** the response does not include `gpt-5.5-pro`

#### Scenario: Codex-native models endpoint serves bootstrap metadata

- **GIVEN** the model registry has no refreshed upstream snapshot
- **WHEN** a client calls `GET /backend-api/codex/models`
- **THEN** entries including the GPT-5.6 variants and existing bootstrap models include representative upstream metadata including client version, context-window, visibility, modality, plan-availability, reasoning/verbosity, speed-tier, and tool-mode fields where known

### Requirement: OpenAI-compatible model metadata preserves the backend input budget explicitly

When serving `GET /v1/models`, the system SHALL expose the upstream backend input/context budget in `metadata.input_context_window`. For models whose reported `metadata.context_window` is not operator-overridden, `metadata.context_window` and `metadata.input_context_window` SHOULD be equal. The system SHOULD expose `metadata.max_output_tokens` for known GPT-5 Codex models when that output-budget value is known; that value MUST NOT be used to inflate `metadata.context_window`.

#### Scenario: /v1/models exposes the 272k backend input budget explicitly

- **WHEN** the upstream model catalog contains a known GPT-5 Codex model with `context_window=272000`
- **THEN** `GET /v1/models` returns that model with `metadata.input_context_window=272000`
- **AND** `metadata.context_window=272000`

#### Scenario: /v1/models exposes the GPT-5.6 backend input budget explicitly

- **WHEN** the upstream model catalog contains a GPT-5.6 variant with `context_window=372000`
- **THEN** `GET /v1/models` returns that model with `metadata.input_context_window=372000`
- **AND** `metadata.context_window=372000`

#### Scenario: Explicit reported-context overrides do not hide the backend input budget

- **WHEN** an operator override sets a model's reported `metadata.context_window` to `515000`
- **AND** the upstream model catalog contains that model with `context_window=272000`
- **THEN** `GET /v1/models` returns that model with `metadata.context_window=515000`
- **AND** `metadata.input_context_window=272000`

#### Scenario: /v1/models exposes max output budget for known GPT-5 Codex models

- **WHEN** `GET /v1/models` returns `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, or `gpt-5.3-codex`
- **THEN** the entry's metadata includes `max_output_tokens=128000`

## ADDED Requirements

### Requirement: GPT-5.6 bootstrap metadata matches the Codex-native contract

Before registry refresh, the system MUST advertise all three GPT-5.6 variants with `context_window=372000`, `max_context_window=372000`, `minimal_client_version=0.144.0`, Fast availability, WebSocket preference, code-mode tools, Responses Lite, original image detail, and their current variant priority and reasoning metadata. Sol MUST use priority 1 and default effort `low`; Terra MUST use priority 2 and default effort `medium`; Luna MUST use priority 3 and default effort `medium`. Sol and Terra MUST advertise ordered efforts `low`, `medium`, `high`, `xhigh`, `max`, `ultra` and `multi_agent_version=v2`; Luna MUST advertise ordered efforts `low`, `medium`, `high`, `xhigh`, `max` and `multi_agent_version=v1`.

#### Scenario: Sol and Terra advertise Codex Ultra metadata

- **GIVEN** the model registry has no refreshed upstream snapshot
- **WHEN** a client reads the Codex-native entries for Sol and Terra
- **THEN** both entries advertise `max` and `ultra` in order
- **AND** both entries advertise `multi_agent_version=v2`

#### Scenario: Luna stops at max reasoning

- **GIVEN** the model registry has no refreshed upstream snapshot
- **WHEN** a client reads the Codex-native entry for Luna
- **THEN** the entry advertises `max`
- **AND** it does not advertise `ultra`
- **AND** it advertises `multi_agent_version=v1`

#### Scenario: Refreshed GPT-5.6 metadata remains authoritative

- **GIVEN** the refreshed snapshot contains a GPT-5.6 entry whose metadata differs from bootstrap
- **WHEN** a model catalog or behavior lookup is performed
- **THEN** the system uses the refreshed entry rather than merging stale bootstrap fields into it
