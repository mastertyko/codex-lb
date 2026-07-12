## MODIFIED Requirements

### Requirement: Persistent HTTP bridge fast-path scheduling preserves causal attribution and bounded fairness
The persistent HTTP Responses bridge relay MUST use cancellation-safe default pending-lock acquisition and the restored receive, queue-wait, eager event-parsing, response/error derivation, and awaited queue-delivery semantics. The relay MUST preserve mutual exclusion, waiter cancellation, response routing, archive attribution, frame order, terminal sentinels, pending cleanup, and queued-request accounting when requests and the upstream reader overlap.

#### Scenario: Ready enqueue remains causally isolated during a prebuffered burst
- **WHEN** a request-enqueue task becomes ready while the relay handles immediately available upstream text frames
- **THEN** every frame is matched and archived against request ownership established before that frame is processed
- **AND** the enqueue task can make progress without changing frame order or allowing the newly enqueued request to claim an earlier frame

#### Scenario: Cancelled pending-lock waiter does not corrupt bridge ownership
- **WHEN** a pending-lock waiter is cancelled while a bridge writer owns the lock and the upstream reader is also waiting
- **THEN** cancellation propagates to that waiter
- **AND** the reader subsequently preserves response routing, archive request ids, frame order, terminal sentinels, pending cleanup, and queued-request accounting

### Requirement: Persistent HTTP bridge lock performance is deterministically measurable
The repository MUST retain an executable HTTP-bridge relay benchmark that invokes the restored production relay and downstream consumer with concurrent enqueue, lock contention, waiter cancellation, receive timeout, and fast and backlogged consumers. The benchmark MUST validate a fixed correctness digest covering routing, archive attribution, frame order, cancellation, timeout, terminal sentinels, pending cleanup, and queued-request accounting before reporting median and p95 nanoseconds per event against a locked reference workload.

#### Scenario: Operator measures the restored HTTP bridge relay
- **WHEN** the HTTP-bridge relay benchmark is executed
- **THEN** it rejects cancellation corruption, cross-request routing, archive misattribution, frame-order drift, terminal-sentinel drift, timeout cleanup drift, and incomplete cleanup
- **AND** it reports repeated post-warmup fast-consumer and backlogged-consumer median and p95 latency metrics
