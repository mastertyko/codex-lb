## ADDED Requirements

### Requirement: Local HTTP bridge session-close failures retain finite attribution
When a local HTTP bridge session close fails a pending request before `response.completed`, the service MUST keep the request visible as `stream_incomplete` and MUST persist failure attribution in the existing request-log fields. The `failure_detail` MUST include exactly one finite close reason from `account_binding_changed`, `capacity_evict`, `creation_aborted`, `idle_prune`, `local_terminal_error`, `registry_detach`, `retire_after_drain`, or `shutdown`, together with the request's actual `draining_until_terminal` value. The service MUST preserve a more specific request failure phase and detail when present, MUST use `downstream` only for a request whose draining value is true, and MUST use `bridge` for an otherwise unattributed non-draining request. The attribution MUST NOT contain raw session, affinity, request, account, API-key, or payload values.

#### Scenario: Idle pruning closes a draining request
- **WHEN** idle pruning closes a bridge session while a pending request has `draining_until_terminal=true`
- **THEN** the failed request remains logged with `error_code=stream_incomplete`
- **AND** `failure_phase` is `downstream` when no more specific phase already exists
- **AND** `failure_detail` records `close_reason=idle_prune` and `draining_until_terminal=true`

#### Scenario: Registry detachment closes a non-draining request
- **WHEN** registry detachment closes a bridge session while a pending request has `draining_until_terminal=false`
- **THEN** the failed request remains logged with `error_code=stream_incomplete`
- **AND** `failure_phase` is `bridge` when no more specific phase already exists
- **AND** `failure_detail` records `close_reason=registry_detach` and `draining_until_terminal=false`

#### Scenario: Existing failure attribution survives local close
- **WHEN** a pending request already has a more specific failure phase or detail before the bridge session closes
- **THEN** the service preserves that attribution
- **AND** the failure detail also records the finite local close reason and actual draining value

### Requirement: WebSocket-backed pending-request cleanup settles reservations before account health
When shared WebSocket-backed cleanup fails pending requests from either the persistent HTTP bridge or direct downstream WebSocket transport, the service MUST settle every remaining request's owned API-key reservation before any account-health mutation. Finite HTTP close-reason attribution MUST remain conditional on an HTTP bridge close reason; reservation-first health ordering, draining exclusion, partial-error finalization, bounded retry, and shutdown ownership MUST apply to both transports. Each non-null initial reservation release MUST be attempted independently. If one or more initial releases fail, the service MUST continue later initial releases, MUST retain failed ownership without restoring it to request states, and MUST schedule at most one cancel-safe background retry task for the call. The retry task MUST retain only each failed reservation and its opaque request-specific identifier, MUST retry failed reservations sequentially exactly once each, and MUST isolate each retry error so one failure cannot prevent later retries. It MUST NOT spawn a nested task per reservation or use an unbounded concurrent gather. Any initial release failure MUST suppress account-health mutation for the batch. A request already marked `draining_until_terminal=true` MUST NOT supply an account-health penalty candidate. When every initial release settles, cleanup MAY apply at most one existing health penalty selected from a non-draining request. Regardless of release outcome, the service MUST finalize every draining and non-draining request with its existing status, response-create gate release, failure event or terminal signal, sentinel where applicable, and request-log attribution; it MUST NOT suppress or reclassify `stream_incomplete`. The shared batch-retry task class MUST remain owned by the service's bounded shutdown drain so shutdown awaits its completion or applies the existing bounded cancellation/await policy before database teardown.

#### Scenario: Draining local close releases without an account-health penalty
- **WHEN** a local bridge close fails one or more pending requests and every request has `draining_until_terminal=true`
- **THEN** every owned API-key reservation is settled
- **AND** no account-health mutation is attempted
- **AND** every request retains its `stream_incomplete` failure and close attribution

#### Scenario: Every remaining reservation settles before any health write
- **WHEN** shared WebSocket-backed cleanup has remaining request states with owned API-key reservations and at least one state is eligible for an account-health penalty
- **THEN** ownership of every remaining reservation is taken exactly once
- **AND** every taken reservation is settled before the account-health write begins

#### Scenario: Mixed draining and non-draining cleanup finalizes every state
- **WHEN** shared WebSocket-backed cleanup contains both draining and non-draining request states
- **THEN** cleanup selects at most one health penalty from a non-draining state after all reservations settle
- **AND** every draining and non-draining state receives its required failure or terminal signal, sentinel where applicable, and request-log finalization

#### Scenario: Non-draining failure retains one post-settlement penalty
- **WHEN** one or more non-draining pending requests retain an error that qualifies for the existing account-health penalty
- **THEN** all remaining reservations settle before health mutation
- **AND** cleanup applies exactly one existing health penalty
- **AND** the failed requests retain their existing error status, event, and request-log behavior

#### Scenario: One initial reservation release fails
- **WHEN** the first of multiple pending reservation release attempts raises an error
- **THEN** every later initial reservation release is still attempted
- **AND** the failed reservation is transferred exactly once to a fresh cancel-safe background release attempt with opaque request-specific attribution
- **AND** the request state retains no reservation ownership and the initial path does not double-release it
- **AND** no account-health mutation is attempted for the unsettled batch
- **AND** every request still receives response-create gate release, failure event and sentinel or terminal emission as applicable, and request-log finalization

#### Scenario: Multiple failed releases use one sequential background retry
- **WHEN** any number of initial reservation release attempts fail in one shared pending-request cleanup call
- **THEN** cleanup schedules at most one cancel-safe background retry task
- **AND** that task retries each failed reservation sequentially exactly once using only opaque request-specific attribution
- **AND** a retry failure for one reservation does not prevent later failed reservations from being retried
- **AND** account health remains untouched and foreground finalization remains complete

#### Scenario: Direct WebSocket cleanup uses the shared settlement contract
- **WHEN** direct downstream WebSocket cleanup fails pending requests without an HTTP bridge close reason
- **THEN** reservation-first health ordering, draining exclusion, partial-error finalization, and bounded retry behave identically to the shared contract
- **AND** cleanup does not invent HTTP bridge close-reason attribution

#### Scenario: Shutdown observes a completing shared batch retry
- **WHEN** a shared reservation batch-retry task remains blocked while `close_all_http_bridge_sessions` performs the service shutdown drain and then completes before the bounded timeout
- **THEN** shutdown awaits its completion and removes the task from service ownership before database teardown

#### Scenario: Shutdown cancels a timed-out shared batch retry
- **WHEN** a shared reservation batch-retry task remains blocked through the bounded `close_all_http_bridge_sessions` shutdown-drain timeout
- **THEN** shutdown explicitly cancels that finite batch-retry task and awaits its terminal cancellation and cleanup
- **AND** the task is done and removed from service ownership before shutdown returns to database teardown
- **AND** the cancelled task cannot resume repository operations after shutdown returns

#### Scenario: Foreground cancellation retains post-take cleanup ownership
- **WHEN** direct-WebSocket or HTTP-bridge cleanup is cancelled after atomically taking one or more request reservations
- **THEN** exactly one explicitly owned post-take task continues every initial release, failed-ownership batch transfer, conditional health decision, and every request finalizer
- **AND** the caller propagates its original cancellation only after that task is terminal or retained by bounded cleanup ownership
- **AND** an initially unsettled batch remains health-neutral while every gate, event, sentinel or terminal emission, and request log still finalizes

#### Scenario: Shutdown drain reaches transitive cleanup quiescence
- **WHEN** an owned post-take task schedules a reservation batch-retry task immediately before the post-take task completes during shutdown
- **THEN** the shutdown drain rescans relevant owned task classes within one bounded deadline and discovers the newly scheduled retry
- **AND** shutdown awaits or applies the retry task's explicit cancel-and-terminal-await policy before returning to database teardown

#### Scenario: Timed-out post-take cleanup retains complete ownership
- **WHEN** an owned post-take task remains active at the bounded shutdown deadline
- **THEN** shutdown applies a finite cancellation-safe policy that cannot abandon an in-flight or unreleased reservation or skip any request finalizer
- **AND** no post-take or reservation-retry repository task survives shutdown return to database teardown

#### Scenario: Cancellation awaits one finalizer operation exactly once
- **WHEN** post-take cancellation arrives while a terminal send, gate release, queue signal, health write, or request-log finalizer operation is blocked
- **THEN** cleanup invokes that finalizer operation exactly once in one local task owned exclusively by the single tracked post-take child
- **AND** the post-take child repeatedly awaits that same local task through shielding until it is terminal, without recreating the operation, wrapping an existing task, or registering independent background ownership
- **AND** post-take cancellation is re-raised only after the operation's single result is consumed and no duplicate side effect is emitted

#### Scenario: Request-log persistence is terminal before shutdown teardown
- **WHEN** post-take shutdown cancellation occurs while the real request-log persistence operation is blocked
- **THEN** cancellation does not reach `_write_request_log` before its single `_persist_request_log` task is terminal
- **AND** request-log persistence is invoked exactly once and is not transferred as a live `proxy-request-log-*` task into `_request_log_tasks`
- **AND** both `_background_cleanup_tasks` and `_request_log_tasks` are quiescent before `close_all_http_bridge_sessions` returns to database teardown

#### Scenario: Unusable upstream retirement precedes terminal publication
- **WHEN** an upstream reader branch determines that its upstream socket is unusable and will fail pending requests with a client-visible terminal event
- **THEN** the reader commits reconnect or retirement state before publishing the first terminal event
- **AND** an immediate follow-up request cannot target the invalidated upstream socket
- **AND** downstream-disconnect, per-request-expiry, transparent-replay, and other paths that intentionally keep or replay the upstream socket do not force reconnect solely because they finalize a request

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


## MODIFIED Requirements

### Requirement: Full upstream conversation archive

The proxy MUST provide an opt-in durable archive of Codex-to-upstream conversation traffic. When enabled, the archive MUST write gzip-compressed newline-delimited JSON records for upstream request payloads, streamed Responses events, compact response payloads, and websocket text or binary frames without performing gzip file I/O in the request event loop during normal operation. The archive writer queue MUST be bounded and MUST apply synchronous write backpressure instead of growing without limit when the background writer is saturated. Archive records MUST include request id, timestamp, direction, traffic kind, transport, account id when known, upstream target metadata, redacted headers, and the full payload or frame body. Credential-bearing headers such as authorization, cookies, proxy authorization, token headers, and API key headers MUST be redacted before persistence. JSON records MUST preserve non-ASCII payload text as UTF-8 rather than Unicode escape sequences. When disabled, no archive file MUST be created by the archive writer.

Direct-WebSocket inbound frames MUST be attributed to the same pending request selected by downstream response matching. A `response.created` frame without a string response id MUST remain unattributed and MUST NOT fall through to the first unassigned pending request.

#### Scenario: Operator enables archive for audit

- **WHEN** `CODEX_LB_CONVERSATION_ARCHIVE_ENABLED=true`
- **AND** a Codex Responses request is proxied upstream
- **THEN** the archive records both the outbound upstream payload and inbound upstream events or response body as gzip JSONL
- **AND** credential-bearing headers are stored as redacted values

#### Scenario: Archive remains disabled by default

- **WHEN** the archive setting is not enabled
- **THEN** the archive writer does not create conversation archive files

#### Scenario: Operator views archived traffic

- **GIVEN** conversation archive files exist as `.jsonl.gz` or legacy `.jsonl`
- **WHEN** an authenticated dashboard operator opens an existing request log detail
- **THEN** the dashboard can find matching archive records by request id across archive files and display payload plus metadata for that request

#### Scenario: Malformed created frame remains unattributed

- **GIVEN** one or more direct-WebSocket requests are pending archive attribution
- **WHEN** upstream sends `response.created` without a string response id
- **THEN** the inbound archive record has no request id attribution
- **AND** no pending request is claimed by that malformed frame
