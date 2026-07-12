## 1. Account eligibility

- [x] 1.1 Let canonical additional-quota mappings defer exact account support to fresh quota telemetry while preserving plan and service-tier gates
- [x] 1.2 Cover an authoritative account catalog that omits Spark while a Pro account has fresh available Spark quota
- [x] 1.3 Prove that an explicit unrelated quota key cannot bypass model account-catalog support
- [x] 1.4 Preserve authoritative account-level service-tier exclusions for catalog-supported accounts while allowing genuine model omissions to use plan-tier fallback
- [x] 1.5 Attach normalized typed provenance only to a selected account admitted through fresh quota-backed catalog omission
- [x] 1.6 Propagate that provenance through HTTP bridge creation and reconnect, and require an exact model, quota-key, and effective-tier match for reuse

## 2. Verification

- [x] 2.1 Run the focused load-balancer and additional-quota test suites
- [x] 2.2 Validate the OpenSpec change artifacts
- [x] 2.3 Reproduce the current-head two-turn bridge reconnect, then verify one upstream transport is reused after the fix
- [x] 2.4 Cover fresh, missing, stale, and exhausted quota evidence plus provenance match boundaries and reconnect propagation
