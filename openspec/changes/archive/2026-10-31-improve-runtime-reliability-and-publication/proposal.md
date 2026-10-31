## Why
The preserved production checkpoint exposed manual publication/privacy checks, incomplete build provenance, probe/projection regressions and failing development gates. Historical request cost details also depend on the current rate card.

## What Changes
- Add a local publication privacy gate and matching CI check over the publication tree and new commits.
- Build deployable images from a clean Git commit with revision and dependency fingerprints.
- Correct probe/projection contracts and restore CI checks without weakening assertions or architectural limits.
- Persist the effective request pricing basis and expose it in request details, preserving legacy and provider totals.

## Impact
Publication tooling, deployment tooling, request-log schema/API/UI, account probes, dashboard projections and their regressions. No production cutover or upstream PR is part of this change. The original checkpoint remains an immutable branch.
