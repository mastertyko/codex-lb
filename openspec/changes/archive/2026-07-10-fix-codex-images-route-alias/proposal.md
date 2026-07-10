## Why

The ChatGPT app submits image generation requests to `POST /backend-api/codex/images/generations`, but codex-lb only exposes the equivalent `POST /v1/images/generations` handler. FastAPI therefore rejects the ChatGPT request locally with HTTP 405 before authentication, account routing, or image generation can run.

## What Changes

- Expose `POST /backend-api/codex/images/generations` as a compatibility alias for the existing Images generation adapter.
- Apply the same request validation, authentication, account selection, usage accounting, response shape, and observability as `POST /v1/images/generations`.
- Keep `POST /v1/images/generations` unchanged and avoid a second image-generation implementation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `images-api-compat`: Extend the compatible image generation contract to the ChatGPT/Codex backend route used by the desktop app.

## Impact

- `app/modules/proxy/api.py`: route registration only; both paths share the existing handler.
- `tests/integration/test_proxy_images.py`: route-alias regression coverage.
- `openspec/specs/images-api-compat`: one additional route compatibility requirement when the change is synced.
- No database migration or new dependency.
