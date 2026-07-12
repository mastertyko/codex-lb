## ADDED Requirements

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
