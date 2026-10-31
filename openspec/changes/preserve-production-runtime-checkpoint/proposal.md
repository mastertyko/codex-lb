## Why

The deployed runtime combines published changes, local integrations and later
image overlays. No existing branch contains its complete source. A portable
checkpoint must preserve the actual deployed bytes and the inputs that produce
its dashboard, without changing the running service or unrelated worktrees.

## What Changes

- Capture the application's source, supporting scripts, registry data and
  migrations from the running image in one dedicated branch.
- Include the dashboard source and frozen dependencies that reproduce its
  deployed assets, plus source provenance and content hashes.
- Add an offline checkpoint verifier and document the build and verification
  evidence, including any limits of reproducing the complete image.
- Preserve deployed behavior, including the existing desktop, quota routing,
  Pro-capacity, pricing, continuity and request-log integrations.

## Capabilities

### New Capabilities

- `runtime-source-checkpoints`: portable, independently verifiable snapshots of
  deployed source and build inputs.

## Impact

This is a preservation branch, not a new deployment or a merge-ready feature PR.
The running service, database, credentials and unrelated working copies remain
unchanged. Runtime source is copied exactly rather than refactored. No account
records, environment secrets, host paths or deployment credentials are included.
