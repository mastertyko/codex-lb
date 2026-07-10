## Context

`POST /v1/images/generations` already implements validation, authentication, account selection, Responses `image_generation` translation, usage settlement, streaming, and telemetry. The ChatGPT app uses the Codex backend prefix and currently calls `POST /backend-api/codex/images/generations`; because that route is unregistered, FastAPI returns 405 before the existing adapter runs.

## Goals / Non-Goals

**Goals:**
- Accept the ChatGPT app's Codex-prefixed generation request.
- Preserve one implementation and identical behavior across both route prefixes.
- Keep existing security, accounting, and observability contracts intact.

**Non-Goals:**
- Add a second image-generation backend.
- Change image edit or variations routes.
- Change supported models, parameter validation, output events, or multi-image limits.

## Decisions

- Register the existing generation handler on both `v1_router` and the Codex `router`. A second decorator is the smallest route-only fix and guarantees both paths invoke the same function.
- Reuse `V1ImagesGenerationsRequest`, `_proxy_images_generation_request`, and both routers' existing `validate_proxy_api_key` and OpenAI error-format dependencies. A forwarding handler or internal HTTP redirect would add an avoidable second hop and could alter authentication or streaming behavior.
- Keep telemetry route labels as `generations`; the alias represents the same bounded image capability rather than a new operation.

## Risks / Trade-offs

- Future path-specific behavior could accidentally diverge if implemented before the shared handler; regression coverage must exercise the Codex-prefixed path through the same adapter.
- FastAPI will expose both paths in generated schema unless explicitly hidden. The Codex route is a supported compatibility surface, so visibility is acceptable.
