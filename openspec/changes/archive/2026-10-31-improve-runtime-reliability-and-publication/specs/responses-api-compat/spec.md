## ADDED Requirements

### Requirement: Codex control requests preserve a single media-type header

For unary Codex control requests, including standalone search and realtime call
creation, the proxy MUST emit at most one case-insensitive `Content-Type` field.
When an inbound media type is present, the proxy MUST forward that value without
rewriting it to JSON and MUST preserve the opaque body bytes. Native requests
MUST retain the first media-type field's spelling and header position. The
contract MUST apply across direct and routed HTTP transports. With no inbound
media type, requests with a body MUST retain the existing JSON default, while
requests without a body MUST omit the synthesized media-type field.

#### Scenario: native standalone search preserves a single JSON media type

- **WHEN** Codex Desktop sends a JSON POST to any supported standalone search path
- **THEN** the upstream request contains exactly one `Content-Type` field with the inbound value
- **AND** the body bytes are unchanged

#### Scenario: non-JSON control body retains its media type

- **WHEN** a native control request carries `content-type: application/sdp`
- **THEN** the upstream request contains one lowercase media-type field in its original position
- **AND** its value remains `application/sdp` without a second JSON field

#### Scenario: header spelling does not create duplicates

- **WHEN** a native or SDK caller supplies a lowercase, PascalCase, or mixed-case media-type header
- **THEN** the control request emits exactly one case-insensitive media-type field

#### Scenario: bodyless control requests omit synthesized media type

- **WHEN** a control request has neither an inbound media type nor a body
- **THEN** the upstream request has no `Content-Type` field

#### Scenario: untyped control bodies retain the existing default

- **WHEN** a control request has a body and no inbound media type
- **THEN** the upstream request has one `Content-Type: application/json` field

### Requirement: Native HTTP tool resends preserve owner-bound context
The HTTP Responses bridge MUST recognize a complete native tool-loop resend on its durable owner when the stored input count and fingerprint match and the response-bound pending-call manifest is exactly settled by matching direct calls and outputs. The classification MUST retain duplicate, unknown-manifest, incomplete-batch and malformed-item rejection. Native item metadata MUST be an object to qualify for this additional proof. Shape-valid developer controls in the verified historical prefix and completed shape-valid assistant commentary before the tool batch MUST NOT prevent this proof. Fresh developer controls and agent-message suffixes MUST NOT gain permission through this proof.

A qualifying fresh bridge MUST send the complete original request on its durable account without a stale injected response anchor. The bridge MUST preserve input, reasoning, compaction, metadata, instructions and prompt cache identity through the existing wire serializer. The verification view MUST NOT replace the transmitted body or authorize account-neutral replay. Implicit preferred-account fallback and owner retirement MUST NOT send an owner-bound request to another account. Conflicting file or turn-state ownership MUST retain existing fail-closed behavior.

Stale-anchor recovery using this proof MUST require the matching durable owner, unchanged payload and durable proof, an operation fence, no previously visible response output, and no prior replay. It MUST attempt at most one unanchored replay on the same account.

#### Scenario: Fresh bridge receives complete native tool history
- **GIVEN** a complete tool-loop resend matches the durable prefix and exact response-bound call manifest
- **WHEN** native metadata or completed assistant commentary precedes its matching tool results and no reusable bridge remains
- **THEN** the original complete input is sent once on the durable account without the stale anchor
- **AND** its cache key and instructions are preserved

#### Scenario: Stale anchor is rejected before visible output
- **GIVEN** the complete native tool history has an unchanged durable owner-bound proof
- **WHEN** its anchor is rejected before visible output and a valid unreplayed operation fence exists
- **THEN** recovery sends the original complete request without the anchor once on that same owner

#### Scenario: Alternate account cannot receive owner-bound context
- **GIVEN** the durable owner of a qualifying native tool resend is unavailable and another account is selectable
- **WHEN** ordinary selection or quarantined-anchor recovery runs
- **THEN** the request fails closed without sending the history to the alternate account

#### Scenario: Incomplete or malformed history does not qualify
- **WHEN** the prefix changes, the manifest is unknown, a parallel call or output is absent, an output is duplicated, commentary or metadata is malformed, or fresh developer control is inserted
- **THEN** the additional owner-bound proof is rejected

#### Scenario: Existing replay fences remain effective
- **WHEN** the operation fence is missing, a replay already occurred, output is visible, or the durable owner no longer matches
- **THEN** the native tool proof does not authorize an unanchored replay

## MODIFIED Requirements

### Requirement: Native Codex preserves upstream failure lifecycle

For a native Codex HTTP/SSE Responses request, a raw upstream transport timeout MUST preserve the native failure lifecycle when it has no retry-exhaustion marker.
An upstream stream EOF without a terminal Responses event and without an internal
retry-exhaustion marker MUST terminate the downstream stream without
synthesizing `response.failed`, `error`, or `[DONE]`. The proxy MUST still
execute reservation, request-log, account-health, and owned-resource cleanup
before propagating the termination. Non-native and OpenAI-compatible clients
MUST retain the existing stable terminal-error shaping.

When codex-lb has exhausted its own transport retries or account replays and
marks the resulting transport terminal with
`_codex_lb_synthetic_transport_failure`, a native Codex HTTP/SSE Responses
request MUST instead receive exactly one terminal `response.failed` event. Its
`error.code` MUST be `rate_limit_exceeded`, and its message MUST begin with a
bounded `Please try again in <N>s.` hint followed by the original upstream code
and message. The egress code and message MUST NOT replace the original
transport code used by account-health, request-log, reservation, or selection
classification. The marker MUST NOT be exposed to the client, and an upstream
`[DONE]` after the marked terminal MUST NOT be forwarded.
After emitting that terminal, every intermediate async stream wrapper MUST
close its inner stream so the retry generator's `finally` handlers release
account leases and unwind the upstream transport.

#### Scenario: Exhausted visible native stream gets one retryable terminal

- **GIVEN** a native Codex HTTP request has received non-terminal upstream SSE
  events and the retry layer exhausts a transport failure
- **WHEN** the retry layer emits one marked synthetic transport terminal
- **THEN** the client receives one `response.failed` with
  `error.code="rate_limit_exceeded"`
- **AND** the message starts with a parseable `Please try again in <N>s.` hint
- **AND** the original transport code remains the internal settlement/log code
- **AND** no marker or `[DONE]` reaches the client

#### Scenario: Exhausted pre-visible native attempts get the same terminal

- **GIVEN** a native Codex HTTP request has no downstream-visible output
- **AND** all eligible transport attempts are exhausted and produce a marked
  synthetic transport terminal
- **WHEN** the public Responses normalizer runs
- **THEN** it emits exactly one retryable `response.failed` event with the same
  code and delay contract

#### Scenario: Native Codex sees a truncated SSE lifecycle

- **GIVEN** a native Codex HTTP request has received a non-terminal SSE event
- **WHEN** upstream closes without a terminal event or retry-exhaustion marker
- **THEN** downstream closes without a synthetic terminal event or `[DONE]`
- **AND** proxy cleanup and failure accounting still complete

#### Scenario: Native give-up closes the lease-holding stream chain

- **GIVEN** a native Codex HTTP request reaches the marked transport terminal
- **WHEN** the public normalizer emits its retryable `response.failed`
- **THEN** the intermediate stream wrappers close their inner generators
- **AND** the retry layer releases the account lease before the request ends

#### Scenario: Local refusal remains a normal terminal

- **GIVEN** the proxy refuses a request before any upstream frame is sent
- **WHEN** it reports the existing local-pre-dispatch refusal
- **THEN** the client receives the existing public refusal code and message
- **AND** it is not relabeled as native retryable transport exhaustion

#### Scenario: Non-native client keeps the terminal umbrella

- **GIVEN** an OpenAI SDK or other non-native client receives the same upstream
  transport terminal
- **WHEN** codex-lb normalizes the stream
- **THEN** the client receives the existing terminal `response.failed` shape

### Requirement: Pre-visible unary refresh/connect failures fail over

For unary proxy requests that have not emitted downstream-visible output, the proxy MUST treat retryable token-refresh or upstream-connect transport failures as account-local transient failures.

This applies to Codex thread-goal requests, Codex control requests,
transcription requests, and file create/finalize requests. When another
eligible account is available within the request budget, the proxy MUST record
the failed account, exclude it from the current request, and retry the unary
operation on the fallback account. The proxy MUST NOT fail over strict
account-owner requests whose upstream resource is bound to the selected account.

For account-routed file operations, the client and service MUST preserve typed transport phase and replay eligibility. Confirmed pre-dispatch connection failures MUST use the existing account failover policy even when the credential-safe message contains no transient-error phrase. Typed transport errors MUST NOT gain replay eligibility from message text. TLS verification failures, ambiguous request failures, response-body failures, and process-wide network failures MUST NOT cause cross-account file retries. A file-finalize operation MUST NOT fail over to another account after any of its polls has returned an upstream response, even if a later poll fails before dispatch.

#### Scenario: Unary refresh transport failure uses another account

- **GIVEN** at least two accounts are eligible for a Codex thread-goal, Codex
  control, transcription, or file-create request
- **AND** the selected account fails during token refresh or upstream connect
  with a retryable transient transport error before downstream-visible output
- **WHEN** another eligible account can complete the request within the request
  budget
- **THEN** the downstream request succeeds from the fallback account
- **AND** the failed account is recorded and excluded from further attempts for
  that request

#### Scenario: Strict file-owner refresh failure fails closed

- **GIVEN** a file-finalize request is pinned to the account that owns the file
- **AND** the pinned account fails during token refresh or upstream connect with
  a retryable transient transport error before downstream-visible output
- **WHEN** another account would otherwise be eligible for proxy traffic
- **THEN** the proxy fails the request with an upstream-unavailable error
- **AND** the proxy does not send the file-finalize operation through another
  account

#### Scenario: Routed file connection refusal uses another account

- **GIVEN** an unpinned file-create request with another eligible account
- **WHEN** the routed transport proves that the selected account's proxy connection failed before dispatch
- **THEN** the proxy excludes that account and completes the file-create request through the eligible fallback within the existing budget

#### Scenario: Routed file replay is denied without safe provenance

- **GIVEN** a routed file request with another eligible account
- **WHEN** the transport reports a TLS verification failure, ambiguous request failure, response-body failure, or process-wide network failure
- **THEN** the proxy returns the transport error without invoking the file operation through another account
- **AND** transient-looking text in the sanitized message does not permit replay

#### Scenario: First file-finalize poll fails before dispatch

- **GIVEN** an unpinned file-finalize operation with another eligible account and no completed upstream poll
- **WHEN** its first routed poll fails with a confirmed pre-dispatch connection refusal
- **THEN** the proxy MAY complete the operation on the eligible fallback account within the existing budget

#### Scenario: Later file-finalize poll fails before dispatch

- **GIVEN** an unpinned file-finalize operation whose first upstream poll returned `status: retry`
- **WHEN** a later routed poll fails with a confirmed pre-dispatch connection refusal
- **THEN** the proxy MUST return an upstream-unavailable error without invoking any poll through another account

#### Scenario: Pinned file-finalize poll fails

- **GIVEN** a file-finalize operation pinned to its owner account
- **WHEN** its first or a later poll fails before dispatch
- **THEN** the proxy MUST fail closed without invoking a poll through another account

### Requirement: Failed precreated HTTP bridge replay retires stale sessions

When an HTTP bridge request is still pending before upstream `response.completed` and the upstream websocket closes or times out before the pending request can be completed, the service MUST fail the pending request terminally and retire the affected bridge session if precreated replay does not reconnect and resend successfully. When the replay was attempted and failed, the terminal the client observes MUST preserve the original upstream failure if upstream had already answered with a status-bearing 429 carrying a quota or rate-limit code, and MUST otherwise fail closed as the synthetic `stream_incomplete` terminal. A preserved terminal MUST carry that upstream error code and its quota metadata, and MUST NOT leave the synthetic status or error overrides in place.
#### Scenario: Precreated replay fails after upstream disconnect

- **WHEN** an HTTP bridge request is pending before `response.completed`
- **AND** the upstream websocket closes before the request completes
- **AND** precreated replay fails to reconnect and resend the request
- **THEN** the pending request is removed from the bridge queue
- **AND** the per-session response-create gate is released
- **AND** the bridge session is closed and removed from local reuse
- **AND** the terminal error preserves the original failure code such as `stream_incomplete` or `upstream_request_timeout`

#### Scenario: Terminal logging failure does not preserve stale bridge ownership

- **WHEN** a failed pending HTTP bridge request is being logged as terminal
- **AND** request-log writing fails
- **THEN** the service still removes the stale bridge session from local reuse
- **AND** the service releases any durable bridge ownership for that stale session

#### Scenario: Concurrent waiter cannot submit on retired stale bridge

- **WHEN** an HTTP bridge request is waiting on a session response-create gate
- **AND** the upstream reader retires that same bridge session after a failed precreated replay
- **THEN** the waiting request or prewarm is rejected before it is appended to pending requests or sent upstream
- **AND** the retired bridge session remains closed and removed from local reuse
- **AND** the post-admission ownership check, pending enqueue, and upstream send are mutually exclusive with stale-session retirement

#### Scenario: Unregistered stale bridge reference cannot submit after admission

- **WHEN** an HTTP bridge request or prewarm holds a stale bridge session reference
- **AND** that bridge session is no longer the registered local owner for its session key
- **THEN** the request is rejected after response-create gate admission and before it is appended or sent upstream
- **AND** response-create gate and admission state acquired by the rejected request is released

#### Scenario: Unregistered closed bridge reference cannot reconnect

- **WHEN** an HTTP bridge request holds a closed stale bridge session reference
- **AND** that bridge session is no longer the registered local owner for its session key
- **THEN** the request is rejected before attempting to reconnect the stale bridge upstream

#### Scenario: Reader crash closes bridge before releasing pending gate

- **WHEN** an HTTP bridge upstream reader crashes while a pending request owns the response-create gate
- **AND** another request or prewarm is waiting on that same gate
- **THEN** the crashed bridge session is marked closed before the pending request gate is released
- **AND** the waiting request or prewarm cannot submit on the crashed bridge
- **AND** the crashed bridge session is removed from local reuse and its upstream resources are closed

#### Scenario: Prewarm cleanup does not consume visible queue slots

- **WHEN** a prewarm request is rejected or interrupted after response-create gate admission
- **AND** a visible HTTP bridge request is still counted in the session queue
- **THEN** prewarm cleanup releases its response-create gate and admission state
- **AND** the visible request queue count is preserved

#### Scenario: A failed replay keeps the status-bearing quota terminal

- **GIVEN** a pre-created bridge request whose upstream terminal is a 429 error
  carrying `rate_limit_exceeded`, `usage_limit_reached`, `insufficient_quota`,
  `usage_not_included`, or `quota_exceeded`
- **WHEN** the bounded pre-created replay is attempted and fails
- **THEN** the client receives the upstream code and error type unchanged
- **AND** the terminal carries the upstream `resets_at` and any other quota
  metadata the upstream envelope provided
- **AND** no synthetic 502 `stream_incomplete` status or code override remains
  on the request state

#### Scenario: A failed replay without a quota terminal stays fail-closed

- **GIVEN** a pre-created bridge request whose upstream terminal carries no
  status-bearing quota answer, such as a capacity or overload code
- **WHEN** the bounded pre-created replay is attempted and fails
- **THEN** the client receives the synthetic `stream_incomplete` terminal
- **AND** the request state keeps its 502 status override
