## MODIFIED Requirements

### Requirement: HTTP bridge startup admission waits are bounded

The proxy MUST apply the configured proxy admission wait timeout to HTTP bridge startup waits for per-session response-create gate acquisition, bridge capacity waiters, and in-flight session creation waiters. When the timeout expires, the proxy MUST reject the request locally with HTTP 429 and an OpenAI-style `proxy_overloaded` error envelope. Timing out while observing another request's pending in-flight session creation MUST evict that in-flight marker when it is still pending so later requests can attempt a fresh bridge session instead of waiting on the same stalled future.

If a request owns in-flight bridge session creation and is cancelled or fails after publishing the in-flight marker but before registering the created session, the proxy MUST remove or settle that in-flight marker. If a session owner later finishes creation after its in-flight marker was evicted, the owner MUST NOT return an unregistered bridge session to the caller.

When a visible HTTP bridge request times out waiting for a per-session response-create gate, the proxy MUST retire the bridge session only if a pending gate holder is still awaiting `response.created`, has not exposed downstream output, and has made no upstream progress for at least the configured stuck-gate retirement threshold. Retirement MUST replace the whole bridge generation rather than releasing the old semaphore for reuse.

#### Scenario: Per-session response-create gate does not open

- **WHEN** a bridged Responses request waits for a session response-create gate
- **AND** the gate does not open before the configured proxy admission wait timeout
- **THEN** the request is rejected locally with HTTP 429
- **AND** the error payload uses `error.code = "proxy_overloaded"`
- **AND** no response-create gate lease is recorded on that request state

#### Scenario: In-flight bridge session creation does not finish

- **WHEN** a bridged Responses request waits on another request's in-flight session creation
- **AND** the in-flight creation does not finish before the configured proxy admission wait timeout
- **THEN** the waiter is rejected locally with HTTP 429 and `error.code = "proxy_overloaded"`
- **AND** the stalled in-flight marker is evicted if it is still pending

#### Scenario: Bridge capacity waiter does not make progress

- **WHEN** the HTTP bridge is at capacity and a request waits for in-flight bridge work to free capacity
- **AND** no capacity becomes available before the configured proxy admission wait timeout
- **THEN** the waiter is rejected locally with HTTP 429 and `error.code = "proxy_overloaded"`

#### Scenario: In-flight owner is cancelled during stale session close

- **WHEN** a bridge session creation owner has published an in-flight marker
- **AND** it is cancelled while closing a stale local bridge session before creating the replacement session
- **THEN** the in-flight marker is removed or settled
- **AND** later requests do not remain blocked on that cancelled owner's future

#### Scenario: Silent pending work blocks a visible gate waiter

- **WHEN** a visible HTTP bridge request receives `response_create_gate_timeout`
- **AND** a pending pre-`response.created` gate holder has received no upstream event for at least the configured threshold
- **THEN** the proxy retires the bridge session so later requests can create a fresh session
- **AND** the waiter is rejected cleanly with `response_create_gate_timeout`

#### Scenario: One upstream event is followed by silence

- **WHEN** a pending gate holder receives an upstream event before `response.created`
- **AND** no later upstream event arrives for at least the configured threshold
- **AND** a visible waiter times out on the same session gate
- **THEN** the proxy retires the stale bridge session

#### Scenario: Old holder continues making progress

- **WHEN** a pending gate holder remains older than the configured threshold
- **AND** matched upstream events continue to arrive within that threshold
- **AND** a visible waiter times out on the same session gate
- **THEN** the proxy does not retire the active bridge session

#### Scenario: Late cleanup belongs to the retired generation

- **WHEN** a stale bridge is retired and a later request creates a replacement session
- **AND** the old upstream reader later releases its request gate
- **THEN** only the retired session's semaphore is released
- **AND** the replacement session's gate state is unchanged
