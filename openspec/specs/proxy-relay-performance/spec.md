# Proxy Relay Performance Specification

## Purpose

Define measurable relay hot-path performance contracts that preserve multiplexing, ownership, cancellation, and scheduler fairness.

## Requirements

### Requirement: Direct WebSocket text frames use one shared parsed representation
The direct Responses WebSocket relay MUST decode each upstream text frame into one parsed payload that is shared by archive ownership and downstream processing. The relay MUST construct a typed OpenAI event model only when the event is terminal and typed usage or error fields are required.

#### Scenario: Multiplexed text burst is parsed once per frame
- **WHEN** the direct relay receives created, delta, done, and terminal text frames for multiplexed responses
- **THEN** archive matching and downstream processing use the same parsed payload for each frame
- **AND** non-terminal frames do not require typed OpenAI event-model construction

### Requirement: Direct WebSocket fast-path scheduling preserves bounded fairness
The direct Responses WebSocket relay MUST preserve mutual exclusion and waiter cancellation for pending-request and downstream-send locks while avoiding an unconditional scheduler checkpoint on every uncontended acquisition. The relay MUST provide a bounded scheduling checkpoint so a ready concurrent request-enqueue task can run before a prebuffered upstream burst fully drains.

#### Scenario: Ready enqueue runs during a prebuffered burst
- **WHEN** an enqueue task becomes ready as the relay starts draining immediately available upstream frames
- **THEN** the enqueue task acquires the pending-request lock before the relay emits the entire burst
- **AND** downstream frame order and archive attribution remain unchanged

#### Scenario: Cancelled contended waiters do not corrupt relay state
- **WHEN** pending-request and downstream-send lock waiters are cancelled while a relay frame is waiting behind them
- **THEN** cancellation propagates to those waiters
- **AND** the relay subsequently emits every frame in order with the correct archive request id
- **AND** terminal processing leaves no pending request ownership

### Requirement: Direct WebSocket relay performance is deterministically measurable
The repository MUST provide an executable benchmark that invokes the real direct-WebSocket relay and downstream processor with multiplexed requests. The benchmark MUST validate a fixed correctness digest before reporting sample count, request count, delta count, total event count, median nanoseconds per event, p95 nanoseconds per event, and a score against a locked reference.

#### Scenario: Operator measures the direct relay
- **WHEN** the direct-WebSocket relay benchmark is executed
- **THEN** it rejects frame loss, byte or order drift, cross-request archive attribution, malformed-created attribution, lock-cancellation errors, and ready-enqueue starvation
- **AND** it reports median and p95 nanoseconds per event over repeated post-warmup samples

### Requirement: Persistent HTTP bridge fast-path scheduling preserves causal attribution and bounded fairness
The persistent HTTP Responses bridge relay MUST preserve mutual exclusion and waiter cancellation for pending-request ownership while avoiding an unconditional scheduler checkpoint on every uncontended lock acquisition. The relay MUST checkpoint only after a received text frame has been fully matched, archived, queued or suppressed downstream, terminally finalized when applicable, and evaluated for retirement. The relay MUST provide a bounded checkpoint so a ready concurrent request enqueue can run before a prebuffered upstream burst fully drains.

#### Scenario: Ready enqueue runs only after the current frame is fully attributed
- **WHEN** a request-enqueue task becomes ready while the relay handles an immediately available upstream text frame
- **THEN** the frame is matched and archived against the pending state that existed when handling began
- **AND** the enqueue task acquires the pending lock before the remaining prebuffered burst fully drains
- **AND** the newly enqueued request can participate only in later frame attribution

#### Scenario: Cancelled pending-lock waiter does not corrupt bridge ownership
- **WHEN** a pending-lock waiter is cancelled while a bridge writer owns the lock and the upstream reader is also waiting
- **THEN** cancellation propagates to that waiter
- **AND** the reader subsequently preserves response routing, archive request ids, frame order, terminal sentinels, pending cleanup, and queued-request accounting

### Requirement: Persistent HTTP bridge lock performance is deterministically measurable
The repository MUST extend the executable HTTP-bridge relay benchmark with concurrent enqueue, lock contention, waiter cancellation, and ready-enqueue fairness cases. The benchmark MUST validate those contracts in its fixed correctness digest before reporting fast-consumer and backlogged-consumer median and p95 nanoseconds per event.

#### Scenario: Operator measures the optimized HTTP bridge lock path
- **WHEN** the HTTP-bridge relay benchmark is executed
- **THEN** it rejects event-loop monopolization, cancellation corruption, cross-request routing, archive misattribution, frame-order drift, terminal-sentinel drift, and incomplete cleanup
- **AND** it reports repeated post-warmup latency metrics against the locked reference workload
