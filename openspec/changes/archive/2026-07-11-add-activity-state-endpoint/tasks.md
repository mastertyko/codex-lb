## 1. Activity API

- [x] 1.1 Add the typed activity response schema, bounded aggregation service, and unauthenticated read-only route.
- [x] 1.2 Add request-scoped activity dependency wiring and register the router in the application.

## 2. Behavioral Coverage

- [x] 2.1 Add route-level tests for unauthenticated access, real warmup-excluded aggregates, response aliases, privacy exclusions, idle state, and window clamping.
- [x] 2.2 Add focused service tests for idle behavior, weighted activity scoring, score bounds, and window clamping.

## 3. Verification

- [x] 3.1 Run focused activity API and service tests.
- [x] 3.2 Run changed-file diagnostics and strict OpenSpec validation.
- [x] 3.3 Verify the live `codex-activityd` poll receives HTTP 200 after deployment.
