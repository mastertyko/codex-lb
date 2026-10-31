## Decisions
Use a standard-library publication wrapper around installed Gitleaks plus a personal-data scan. Review exceptions narrowly using content fingerprints, never whole-directory exclusions. Read-only scans redact values and fail closed on missing tooling or unresolved revisions. Pre-push derives each pushed range from Git hook input; CI uses explicit immutable base/head commits.

Build tooling exports a clean commit to an isolated temporary build context, labels the image with its revision and frozen-input digests, and writes a portable receipt with no host data. It builds locally and does not deploy or publish by default.

Store one nullable JSON pricing basis per request: versioned model rate card fingerprint and the effective input/cache/output/write rates. Compute totals and snapshots from the same resolved rates. Old rows remain nullable; do not invent historical provenance. Model-source overrides retain their own persisted totals.

Keep shared quota eligibility outside transport implementations. Fix stale test doubles using typed fixtures/assertions, not blanket type suppressions. Preserve recent equal-weight usage samples while bounding the older EWMA tail.

## Verification
Meaningful CLI tests cover secret/personal-data rejection (including removed-in-a-later-commit values), redaction and clean-build refusal. Pricing tests cover catalog changes after insertion, provider overrides, missing data and migration roundtrips on temporary databases. Run the full repository local gate and record each result; do not weaken gates to claim green.
