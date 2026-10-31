## Why

Successful standalone Codex web searches currently appear as ordinary requests with an empty model and no upstream transport. Operators cannot distinguish them from incomplete inference logs.

## What Changes

- Persist the existing `codex_control_alpha_search` operation as the request kind for standalone search.
- Record HTTP upstream transport when a search reaches the upstream control client.
- Render these requests as `Web search` in the dashboard table and details without inventing model, usage, or cost values.
- Preserve unidentified historical rows and unrelated control-request behavior.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `proxy-runtime-observability`: identify standalone search in persisted request logs and dashboard rendering.

## Impact

The Codex control service, recent-request table, locale labels, and focused route/UI regressions change. No schema, configuration, search-response, routing, or authentication changes are needed. Related search routing/media-type work in #2128 and #2513 addresses a separate concern.
