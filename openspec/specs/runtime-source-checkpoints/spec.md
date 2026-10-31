# Runtime Source Checkpoints Specification

## Purpose
Define portable, verifiable snapshots of deployed application source.

## Requirements

### Requirement: Exact runtime source checkpoint
The checkpoint SHALL contain byte-identical application source, migration files,
supporting runtime scripts and registry data from its recorded image.

#### Scenario: Verify source content
- **WHEN** the checkpoint verifier checks a source tree
- **THEN** every recorded runtime file SHALL match its SHA-256 digest
- **AND** a missing, changed or additional application source file SHALL cause verification to fail

### Requirement: Reproducible dashboard content
The checkpoint SHALL preserve the frontend source and frozen build inputs used
to reproduce the recorded deployed assets.

#### Scenario: Verify a frontend rebuild
- **WHEN** the dashboard is rebuilt using the recorded toolchain and lockfile
- **THEN** the complete generated file set and every file's SHA-256 digest SHALL match the asset manifest

### Requirement: Explicit provenance boundaries
The checkpoint SHALL record the observed image digest, schema head, native
binary digest and verified build evidence without including secrets, account
records or private personal data, and SHALL distinguish source parity from complete image reproducibility.

#### Scenario: Read verification evidence
- **WHEN** an operator reads the checkpoint's verification record
- **THEN** source, dashboard, schema, native and test results SHALL be reported separately
- **AND** incomplete or failing checks SHALL remain explicitly identified

#### Scenario: Review publication contents
- **WHEN** a checkpoint is prepared for publication
- **THEN** the complete publication tree and newly published commits SHALL be reviewed for secrets and private personal data
- **AND** operational logs, credentials, account data and private operator identifiers SHALL be excluded

### Requirement: Non-mutating production capture
Checkpoint capture and verification SHALL preserve the production container,
database and unrelated working copies.

#### Scenario: Finish a checkpoint
- **WHEN** capture and local verification finish
- **THEN** production image identity, container start time and restart count SHALL remain unchanged
- **AND** unrelated tracked and untracked source content SHALL remain unchanged
