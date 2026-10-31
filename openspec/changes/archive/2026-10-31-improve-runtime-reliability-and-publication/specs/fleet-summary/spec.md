## ADDED Requirements

### Requirement: Conservative and bounded forecast inputs
Fleet pace SHALL be unavailable when a fresh eligible weekly usage stream has unknown capacity. Projection history reads SHALL preserve every sample inside the equal-weight recent window and bound older samples per account to the configured EWMA tail, consistently across supported databases.

#### Scenario: Unknown weekly capacity
- **WHEN** an eligible account reports fresh weekly usage without known capacity
- **THEN** fleet pace SHALL not present a complete fleet forecast

#### Scenario: Dense older history
- **WHEN** history exceeds the EWMA tail outside the recent window
- **THEN** the fetch SHALL retain the recent samples and only the newest permitted older samples with equivalent forecast results
