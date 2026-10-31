## ADDED Requirements

### Requirement: Request logs identify and filter operational request types
The dashboard MUST label known non-normal request kinds, including Prewarm, Warmup, Compaction, Realtime, and Web search. The request-log API and dashboard MUST support repeated `requestKind`, `transport`, and `upstreamTransport` filters. Values within one filter MUST be combined with OR and different filters with AND. Filtering MUST preserve pagination totals, existing access restrictions, URL state, and reset behavior. Unknown transport selection MUST include unrecorded or unrecognized transport values. Selecting Warmup MUST include legacy `limit_warmup` rows. Free-text search MUST match recorded request kind and transport and the English Web search label.

#### Scenario: Filter prewarm over WebSocket
- **WHEN** the user selects Prewarm and upstream WebSocket
- **THEN** only matching rows and their filtered total are returned
- **AND** reloading preserves the filters and Reset clears them

#### Scenario: Mixed transport and legacy rows
- **WHEN** the user selects unknown upstream transport or Warmup
- **THEN** the corresponding filter includes missing upstream values or legacy limit-warmup rows respectively
- **AND** historical missing metadata is not inferred from the model or downstream transport

### Requirement: Compaction and warmup record attempted upstream transport
Compaction and warmup request logs MUST record upstream HTTP once the upstream request is attempted, including failed upstream attempts. Rejection before dispatch MUST leave upstream transport unrecorded. Existing routing, reservation settlement, error handling, and request-kind behavior MUST remain unchanged.

#### Scenario: Upstream succeeds or rejects a request
- **WHEN** a compaction or warmup request reaches the HTTP upstream client
- **THEN** its request-log row records upstream HTTP independently of the resulting success or error

#### Scenario: Request never reaches upstream
- **WHEN** account preparation or admission rejects the request before dispatch
- **THEN** the row does not claim an upstream HTTP attempt

### Requirement: Request details expose recorded diagnostic measurements
Request-log responses MUST expose nullable response-created, first-upstream-event, response-create-gate-wait, and bridge-queue-wait timings from existing persisted values. The detail view MUST show available phase timings and existing failure phase, failure detail, exception type, upstream status, upstream error code, and bridge stage. Zero timing values MUST remain distinguishable from missing measurements. First-upstream-event timing MUST NOT be substituted for missing TTFT.

#### Scenario: Diagnose a failed request
- **WHEN** a selected request includes failure metadata and measured phase timings
- **THEN** its details show those values, including a recorded zero-millisecond wait
- **AND** absent values are not presented as measured zeroes

### Requirement: Small positive estimated request costs remain visible
The request-log table MUST distinguish a positive estimated cost that rounds below one cent from exact zero. Request details MUST show estimated USD costs with up to six fractional digits and use a less-than indicator for smaller positive amounts. These display changes MUST NOT change recorded cost or pricing calculations.

#### Scenario: Prewarm has a small positive estimated cost
- **WHEN** a request has estimated cost USD 0.00002
- **THEN** the table shows less than USD 0.01 and details show USD 0.00002
- **AND** an exact zero still displays as zero and unknown cost remains unavailable
