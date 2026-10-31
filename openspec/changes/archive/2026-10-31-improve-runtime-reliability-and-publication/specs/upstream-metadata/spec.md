## ADDED Requirements

### Requirement: Immutable request pricing basis
New subscription request costs SHALL persist a versioned pricing basis containing the resolved model rate-card fingerprint and effective input, cached-input, cache-write and output unit prices used for that request. Request detail reads SHALL use the captured basis even after catalog changes. Existing rows without a basis SHALL remain supported without fabricated historical provenance, and provider-supplied totals SHALL remain authoritative.

#### Scenario: Catalog changes after a request
- **WHEN** the current catalog changes after a priced request is stored
- **THEN** its stored total, cost breakdown and captured unit prices SHALL remain unchanged

#### Scenario: Legacy or provider row
- **WHEN** no trustworthy captured pricing basis is available
- **THEN** the response SHALL not claim captured unit prices and SHALL preserve its stored total
