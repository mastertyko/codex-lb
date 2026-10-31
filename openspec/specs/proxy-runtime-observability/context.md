# Proxy Runtime Observability Context

## Purpose and Scope

This capability defines what operators should be able to see in the live server console while debugging proxy traffic.

See `openspec/specs/proxy-runtime-observability/spec.md` for normative requirements.

## Decisions

- **Timestamps are always on:** timestamped console logs are a baseline operator need, not a debug-only feature.
- **Request tracing is opt-in:** outbound request summary and payload tracing remain configurable because payload logs can be noisy or sensitive. Since issue #1340 phase 1 the switch is the single `CODEX_LB_TRACE` comma-separated channel list (`shape`, `shape_raw_cache_key`, `payload`, `service_tier`, `upstream_summary`, `upstream_payload`); empty default = all off. It is an incident-debugging knob for interactive use only.
- **Error logs must be correlated:** request id, endpoint, status, code, and message are the minimum useful fields for debugging 4xx/5xx failures.
- **Prewarm observability is outcome-only:** the Codex HTTP-bridge prewarm canary experiment finished, so its bucket/cohort dimensions were retired (issue #1340 phase 4). The `codex_lb_http_bridge_prewarm_total` counter is labelled by `outcome` only, request logs record `prewarm_status` / `prewarm_latency_ms` (statuses: `not_applicable`, `skipped`, `success`, `timeout`, `error` — `canary_miss` no longer occurs). The legacy `prewarm_canary_bucket` / `prewarm_eligible_reason` request-log columns stayed declared but unwritten through v1.22–v1.24; `retire-prewarm-canary-column-mappings` removed them from the ORM model and allow-listed the retained physical columns in the schema-drift gate, because a previous-release replica still maps them and renders explicit NULLs in its INSERTs while the migration Job runs ahead of the workload roll. The Alembic drop revision ships the release after (see the next-release queue in `openspec/specs/deployment-installation/context.md`).
- **TTFT datasource selection stays in Grafana:** the Helm chart packages the
  TTFT dashboard but does not provision a PostgreSQL datasource or its
  credentials. The visible, single-select `DS_SQL` variable keeps
  installation-specific datasource UIDs out of chart values while routing all
  four SQL panels through one explicit selection.

## Operational Notes

- Use request ids to correlate inbound proxy logs, outbound upstream traces, and client-visible failures.
- Prefer summary tracing in normal debugging sessions; enable payload tracing only when the exact normalized outbound request matters.
- For direct compact `5xx` failures, look for `proxy_compact_failure` alongside `upstream_request_complete`; together they show the compact failure phase, failure detail, exception type, retry metadata, and affinity source.
- After the Grafana sidecar imports the TTFT dashboard, select the ordinary
  PostgreSQL datasource that points to the codex-lb database from the visible
  **PostgreSQL** dropdown. A datasource registered only as a frontend runtime
  plugin is not listed by Grafana's datasource variable.
- Timeout invariant violation logs describe startup `Settings` and imported
  constant validation only. They intentionally avoid request-scoped overrides,
  runtime-derived effective timeout values, payloads, API keys, access tokens,
  raw affinity keys, account emails, and other high-cardinality identifiers.

## Affinity decisions in request logs

Issue #2349 adds three nullable columns to existing request logs: `sticky_key_source`, `sticky_kind`, and `sticky_key_hash`. They work without trace settings. Callers with `conversations:read` permission can also read them as `stickyKeySource`, `stickyKind`, and `stickyKeyHash` in `GET /api/request-logs`. Responses without that permission hide all three fields through the existing sensitive-metadata gate.

The hash is the first 16 lowercase hexadecimal characters of SHA-256 over the resolved selection key encoded as UTF-8. For example, a resolved key of `abc` records `ba7816bf8f01cfea`. Session selection keys can differ from raw session headers, so hashing the header separately does not reproduce that value. The metadata never stores raw keys or prompts, even when raw-key tracing is enabled. A hash supports equality grouping, but it is not protection against guessing low-entropy keys. Existing request-log retention applies.

Direct streaming rows retain their existing attempt granularity. Compact records its final operation, while native WebSocket and HTTP bridge rows describe the settled or failed request state. A row covering several sends records its final policy, not an intermediate decision history. Existing recovery can clear a key; that produces a null hash while retaining the original source classification. Metadata alone does not explain hard-owner precedence, rerouting, or account-health decisions.

Rows before affinity resolution, historical rows, auxiliary control/file/transcription/realtime/warmup rows, and external-model-source rows can have all three fields null. This means observation was unavailable. An explicit no-affinity observation uses source `none`; its kind and hash are null. No historical decision is reconstructed.

For a bounded administrator query:

```sql
SELECT sticky_key_source, sticky_kind, sticky_key_hash, COUNT(*) AS rows
FROM request_logs
WHERE requested_at >= CURRENT_TIMESTAMP - INTERVAL '1 day'
GROUP BY sticky_key_source, sticky_kind, sticky_key_hash;
```

## Authentication migration convergence

The affinity history converges with dashboard roles, users, the final compatibility-credential projection and audit actor columns through a no-op merge. Published revisions remain unchanged. Databases already on the authentication branch retain their current credentials and session generations; the earlier credential projection is not replayed on merge-only reupgrade. Databases on the older affinity history run the existing authentication backfills once. Ledgerless schema bootstrap retains those migrations' existing legacy-credential projection behavior.

The subsequent invite migration converges through a second no-op join. Pending, consumed and revoked invite rows retain their hashes, expiry/consumption/revocation times, creator snapshots and flags. The older affinity history creates an empty invite table through the unchanged upstream migration.

## Standalone web search labels

Standalone Codex `alpha/search` calls are control operations with no inference usage recorded by this path. Their request logs use `codex_control_alpha_search`, which the English dashboard renders as `Web search` in the model cell and request-kind details. The stored model remains empty, so model filters and pricing do not acquire a fictitious model. For example, a successful dispatched search appears as `Web search`, downstream `HTTP`, upstream `Up HTTP`, status `OK`, and unavailable token/cost values.

Upstream HTTP is recorded at control-client dispatch. An upstream rejection keeps HTTP plus its existing error status; an account-selection or route-resolution failure before dispatch keeps upstream transport unknown. Search response bodies, routing, and authentication retain the existing control-request contract.

Older rows cannot be safely identified from an empty model alone because other control operations share that shape. They retain their original labels and transport metadata. Backend and frontend changes belong in the same release because the dashboard validates the explicit request-kind values it accepts. No database migration or configuration is required. See [the requirements](spec.md#requirement-standalone-web-search-is-identifiable-in-request-logs).

## Request-log diagnostics and filtering

Known operational kinds have friendly labels beside their recorded model. Repeated `requestKind`, `transport` and `upstreamTransport` filters combine values within a dimension with OR and dimensions with AND. The dashboard retains them in its URL and clears them with Reset. For example, `requestKind=prewarm&upstreamTransport=websocket` isolates prewarm calls using upstream WS. Warmup includes legacy `limit_warmup`; unknown transport includes null and unrecognized values. Existing account, API-key and conversation permission boundaries still apply.

Counts and facets use the same filters. Kind/transport-filtered counts bypass demand aggregates that lack those dimensions, and their cache keys include all three dimensions. Free-text search also matches recorded type/transport and the English Web search label.

Compaction and warmup record upstream HTTP at client dispatch. Preparation, account refresh, routing or admission failures before dispatch retain null; a failed dispatched request retains HTTP. Historical missing values are not backfilled. Compaction retains its existing metadata-based request-kind classification.

Details show recorded response-created, first-upstream-event, response-create-gate-wait and bridge-queue-wait measurements, along with available failure phase/detail, exception type, upstream status/error code and bridge stage. An explicit zero means a measured zero; missing phase fields are omitted and missing TTFT stays unavailable. First-upstream-event is a control/event timing, not an inferred first model token.

Request-log cost display uses `< $0.01` for positive costs that would otherwise round to zero and up to six decimal places in details. For example, a USD 0.00002 prewarm estimate is visible as `$0.00002` in details. These remain estimates; no pricing or settlement calculation changes.

### Cost precision and pricing-tier provenance

The request-log API preserves unrounded costs and available components until the dashboard formats them. A two-token Luna prewarm estimated at USD 0.0000002 therefore remains positive and displays `< $0.000001` in details. Exact zero and missing cost remain distinct. The cost breakdown uses an approximation sign because its components are rounded separately for display.

Price tier is derived from the recorded pricing tier; requested and upstream-reported tiers are displayed separately. For requested `priority` and reported/recorded `default`, the price tier is Standard and the basis is upstream-reported. For requested/recorded `ultrafast` with reported `default`, the price tier is Ultrafast and the requested basis is explicitly unconfirmed. Missing or unrecognized recorded tiers stay unknown, and external model-source pricing is identified separately.

This presentation describes an API-equivalent token estimate, not measured subscription consumption or an invoice. It does not establish execution speed from a requested tier. Saved totals remain authoritative when a catalog changes; relative floating-point tolerance allows harmless representation differences in matching breakdowns without equating a positive microcost with zero. Presentation changes do not trigger historical cost rewrites or pricing-tier changes.
