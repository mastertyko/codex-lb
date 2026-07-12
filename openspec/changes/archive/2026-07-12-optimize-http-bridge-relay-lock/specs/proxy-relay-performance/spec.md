## ADDED Requirements

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
