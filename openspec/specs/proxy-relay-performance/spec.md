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

### Requirement: Persistent HTTP bridge scheduling preserves beta.3 ownership semantics
The persistent HTTP Responses bridge relay MUST preserve the verified beta.3 scheduling implementation unchanged: cancellation-safe default pending-lock acquisition, `asyncio.wait_for` receive and event-queue waits, eager event parsing and response/error derivation, and awaited queue delivery. The scheduling path MUST remain byte- and semantically aligned with beta.3 apart from separately required cleanup and attribution behavior outside that path, MUST NOT add an explicit frame-count scheduler checkpoint, and MUST NOT require a ready enqueue to run before a finite prebuffered burst drains. The relay MUST preserve mutual exclusion, waiter cancellation, response routing, ownership, archive attribution, frame order, terminal sentinels, pending cleanup, and queued-request accounting.

#### Scenario: Finite prebuffered burst preserves causal ownership and order
- **WHEN** the relay handles a finite burst of immediately available upstream text frames
- **THEN** every frame is matched and archived against the request ownership established when that frame is processed
- **AND** streaming and backlogged consumers receive the same routed frames in the same order with the same terminal sentinels and cleanup
- **AND** correctness does not depend on a concurrent enqueue running before the finite burst drains

#### Scenario: Cancelled pending-lock waiter does not corrupt bridge ownership
- **WHEN** a pending-lock waiter is cancelled while a bridge writer owns the lock and the upstream reader is also waiting
- **THEN** cancellation propagates to that waiter
- **AND** the reader subsequently preserves response routing, archive request ids, frame order, terminal sentinels, pending cleanup, and queued-request accounting

### Requirement: Persistent HTTP bridge baseline performance is deterministically measurable
The repository MUST retain an executable HTTP-bridge relay benchmark that invokes the unchanged beta.3 production relay and downstream consumer with lock contention, waiter cancellation, receive timeout, and fast and backlogged consumers. The benchmark MUST validate a fixed correctness digest covering routing, ownership, archive attribution, frame order, cancellation, timeout, terminal sentinels, pending cleanup, and queued-request accounting before reporting median and p95 nanoseconds per event against a locked reference workload. It MUST NOT require a ready enqueue to run before a finite prebuffered burst drains or treat scheduler timing as live-safety proof.

#### Scenario: Operator measures the beta.3 HTTP bridge relay
- **WHEN** the HTTP-bridge relay benchmark is executed
- **THEN** it rejects cancellation corruption, cross-request routing, ownership drift, archive misattribution, frame-order drift, terminal-sentinel drift, timeout cleanup drift, and incomplete cleanup
- **AND** a finite prebuffered burst may validate routing and order without asserting a production scheduler yield
- **AND** it reports repeated post-warmup fast-consumer and backlogged-consumer median and p95 latency metrics
