## Context

See [proposal.md](proposal.md). The control service already derives `codex_control_alpha_search` for account-selection diagnostics, but omits it and upstream transport from the persisted log. Existing database and API fields accept these values.

## Goals / Non-Goals

Connect this existing operation identity to the request table and detail labels. Keep search forwarding, routing, authentication, other control operations, and historical rows unchanged.

## Decisions

- Persist the derived kind only for `alpha/search`; broad reclassification of all control operations would exceed this fix.
- Set upstream HTTP metadata immediately before dispatch, after account and route resolution. Pre-dispatch failures retain unknown transport.
- Use the request kind for the localized display label. Do not put `Web search` in the model column in storage: it is not a model and must not affect model filters or pricing.
- Reuse the existing table transport renderer. Separate transport-label work in #2624 is not a prerequisite.
- Do not backfill from empty models: other non-inference operations have the same empty fields, so that heuristic would mislabel them.

## Risks / Trade-offs

Historical searches keep their old appearance because their operation identity was not stored. Route tests cover success, upstream failure, and no-account rejection; UI tests cover explicit search identity and unidentified legacy rows. Existing control/realtime tests protect adjacent logging and privacy behavior.
