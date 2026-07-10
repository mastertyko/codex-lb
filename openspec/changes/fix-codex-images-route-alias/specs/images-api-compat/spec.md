## ADDED Requirements

### Requirement: Codex backend image generation route compatibility

The system SHALL expose `POST /backend-api/codex/images/generations` as a compatibility alias for `POST /v1/images/generations`. The alias MUST accept the same OpenAI Images generation request shape and MUST use the same authentication, validation, account-selection, Responses `image_generation` translation, usage-accounting, response-formatting, and observability code paths as the `/v1` route.

#### Scenario: ChatGPT app image generation reaches the existing adapter

- **WHEN** an authenticated client sends `POST /backend-api/codex/images/generations` with `model=gpt-image-2` and a non-empty `prompt`
- **THEN** the request is processed by the existing image generation adapter instead of being rejected with HTTP 405
- **AND** the adapter issues its internal Responses request with an `image_generation` tool

#### Scenario: Codex and v1 routes return the same contract

- **WHEN** equivalent valid requests are sent to `POST /backend-api/codex/images/generations` and `POST /v1/images/generations`
- **THEN** both routes apply the same validation and return the same JSON or streaming response contract
