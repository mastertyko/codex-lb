## 1. Route Implementation

- [x] 1.1 Register `POST /backend-api/codex/images/generations` on the existing image generation handler without duplicating adapter logic
- [x] 1.2 Smoke-test the Codex-prefixed route through the ASGI application and confirm it no longer returns 405

## 2. Regression Verification

- [x] 2.1 Add focused integration coverage proving the Codex-prefixed and `/v1` generation routes share request translation and response behavior
- [x] 2.2 Run the focused image proxy tests and validate the OpenSpec change
