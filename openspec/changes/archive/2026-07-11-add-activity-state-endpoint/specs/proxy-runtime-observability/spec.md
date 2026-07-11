## ADDED Requirements

### Requirement: Privacy-safe activity state endpoint

The system SHALL expose a read-only `GET /api/activity/state` endpoint for local and personal observability clients. The endpoint SHALL be reachable without dashboard-session or API-key credentials so credentialless local pollers can use it. The endpoint SHALL derive its response from warmup-excluded request-log aggregates and SHALL return only aggregate activity data: a normalized activity value, source and freshness status, generated/since timestamps, the effective query window, request and error counts, token totals, and aggregate cost.

The normalized `activity` value MUST be between `0.0` and `1.0` inclusive. The response MUST NOT contain request ids, account ids, API keys, model names, prompts, response text, error messages, top-error values, or other per-request correlation data.

The scoring calculation SHALL treat `cachedInputTokens` as a subset of `inputTokens`, SHALL count the cached subset at 25% of uncached input weight without double-counting it, and SHALL reserve 85% of the normalized score for the strongest non-error signal plus 15% for error pressure. A saturated non-error signal together with saturated error pressure SHALL produce `activity = 1.0`.

#### Scenario: Credentialless poller reaches the endpoint

- **WHEN** a client sends `GET /api/activity/state` without dashboard-session credentials, an API key, or an `Authorization` header
- **THEN** the endpoint returns HTTP 200 with the aggregate activity response

#### Scenario: Recent request logs are aggregated

- **WHEN** a client requests `/api/activity/state` and non-warmup request logs exist inside the effective window
- **THEN** the response reports aggregate request, error, token, cached-token, and cost values from those logs
- **AND** `activity` is a bounded value in the inclusive range `0.0` through `1.0`
- **AND** warmup request logs do not affect the response

#### Scenario: Idle runtime reports zero activity

- **WHEN** no qualifying request-log activity exists inside the effective window
- **THEN** the endpoint returns HTTP 200
- **AND** `activity` equals `0.0`
- **AND** all aggregate counters and aggregate cost equal zero
- **AND** the source status indicates that the live query succeeded rather than that the result is stale

#### Scenario: Response excludes sensitive and per-request data

- **WHEN** qualifying request logs contain account identifiers, API-key identifiers, model names, error details, prompts, or response content
- **THEN** the endpoint response contains none of those values or fields
- **AND** the response cannot be used to correlate an individual request

#### Scenario: Cached input is weighted once

- **WHEN** aggregate input tokens include a cached-input subset
- **THEN** the cached subset is removed from the uncached-input portion before scoring
- **AND** the cached subset contributes at 25% of uncached input weight

#### Scenario: Full activity is reachable

- **WHEN** at least one non-error activity signal and the error-pressure signal both reach their full thresholds
- **THEN** the endpoint reports `activity = 1.0`

#### Scenario: Query window is bounded

- **WHEN** a client omits `windowSeconds`
- **THEN** the service uses a 120-second effective window

- **WHEN** a client requests a window shorter than 10 seconds or longer than 3600 seconds
- **THEN** the service clamps the effective window to 10 seconds or 3600 seconds respectively
- **AND** the response reports the clamped effective window
