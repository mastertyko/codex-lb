## MODIFIED Requirements

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
