## ADDED Requirements

### Requirement: Normalize forbidden capture storage roots
The isolated body capture tool SHALL reject destinations beneath forbidden temporary roots after resolving both the destination and each forbidden root. A system alias for a temporary directory SHALL not bypass the storage policy.

#### Scenario: Temporary root is a filesystem alias
- **GIVEN** a forbidden temporary root resolves to a different absolute path
- **WHEN** a capture destination is inside that resolved directory
- **THEN** the tool rejects the destination before starting capture
