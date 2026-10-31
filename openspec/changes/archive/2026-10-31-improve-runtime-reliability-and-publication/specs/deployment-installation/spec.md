## ADDED Requirements

### Requirement: Clean source build provenance
The repository SHALL provide a local image build command that requires a clean Git tree, exports only the selected commit, preserves frozen dependency inputs and labels the result with its full source revision and dependency fingerprints. A portable build receipt SHALL identify the source revision, image digest and dependency inputs without credentials, host paths or personal data.

#### Scenario: Dirty build source
- **WHEN** the source checkout contains staged, unstaged or untracked changes
- **THEN** the provenance build SHALL fail before invoking Docker

#### Scenario: Completed build
- **WHEN** a clean-commit image build succeeds
- **THEN** the receipt SHALL match the inspected image labels and digest

### Requirement: Preserve additive runtime columns during ledger recovery
When an older or missing Alembic ledger is reconciled over an existing runtime schema, the upgrade SHALL preserve an existing legacy Pro allowance column and its values. It SHALL apply every preceding pending migration before recording the already applied additive revision. Relative upgrade targets SHALL retain their original meaning. An incompatible existing column SHALL fail closed instead of being silently accepted.

#### Scenario: Ledger rewound over existing runtime additions
- **GIVEN** the runtime schema already contains legacy Pro allowance and captured pricing basis columns
- **WHEN** the operator upgrades after losing or rewinding the migration ledger
- **THEN** the upgrade reaches the requested revision without duplicate-column errors
- **AND** existing allowance selections, captured prices and dashboard credentials remain unchanged
