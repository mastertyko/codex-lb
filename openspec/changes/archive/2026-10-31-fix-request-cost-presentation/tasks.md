## 1. Implementation

- [x] 1.1 Preserve positive cost precision at the API boundary and retain authoritative saved totals, with route regression coverage.
- [x] 1.2 Show price tier and estimate basis using existing requested/reported tiers; cover disagreement, aliases, missing metadata and external sources.
- [x] 1.3 Show independently rounded cost breakdowns as approximate and update all existing locales.

## 2. Verification and delivery

- [x] 2.1 Pass focused backend/frontend tests, lint, typecheck, build and strict OpenSpec validation; inspect rendered desktop/mobile views.
- [x] 2.2 Build and verify a focused overlay on the actual production image; deploy using the authorized image-only cutover.
- [x] 2.3 Verify production health, unchanged saved costs and live microcost/tier presentation; sync the spec and archive the verified change.
