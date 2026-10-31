## Verification

Both added requirements and their four scenarios are covered. The route regression failed on the original implementation for all three outcomes; the search table regression failed on the missing label. The final implementation passes:

- `.venv/bin/python -m pytest tests/integration/test_proxy_api_extended.py tests/integration/test_request_logs_api.py tests/unit/test_request_logs_service.py -q --tb=short --show-capture=no`: 121 passed against a disposable SQLite database. After adding explicit null usage/cost assertions, the three search metadata cases passed again.
- `bun run test src/features/dashboard/components/recent-requests-table.test.tsx src/features/dashboard/schemas.test.ts src/i18n/index.test.ts src/__integration__/dashboard-flow.test.tsx`: 90 passed. The new component regression parses the real request schema before rendering.
- `bun run typecheck`, affected ESLint, Ruff check/format and backend `ty check`: passed.
- `bun run build`: passed.
- Strict OpenSpec validation of this change and `proxy-runtime-observability`: passed. Whole main-spec validation: 67 passed, zero failed.
- Headless browser QA with synthetic API fixtures: table label, recorded upstream HTTP, opening and closing details, desktop and mobile rendering, no application console errors or warnings. Before/after screenshots are external review artifacts.

The main specification contains the exact delta; its pre-existing text and context are unchanged. At the end of local verification, no full repository CI run, commit, publication, or production deployment had been performed. Existing legacy rows remain unidentified as explained in the capability context.

## Authorized deployment on 2026-10-31

Following explicit user authorization, the fix was deployed to Mac mini in image-only mode. The existing production frontend was reproduced byte-for-byte across all 90 assets before applying the fix, preserving its upstream-transport details and other private dashboard changes. The adapted frontend passed 100 focused tests, typechecking, its production build, and desktop/mobile browser checks. The backend logging file is identical to the tested implementation; image verification confirmed that every other Python source file and the image's runtime configuration remained unchanged.

The cutover completed successfully in 17.678 seconds. Image `sha256:5dd5f7f75090932f1d31d4a7ec6d437890c8eb31bb58bd436a52d56a1cc80538` retains Alembic revision `20260930_000000_add_pro_legacy_allowance`. The image/revision-pinned live verifier passed, all three readiness routes returned HTTP 200, PostgreSQL was not restarted, and initial startup logs contained no ERROR, CRITICAL, or Traceback lines. All 90 served frontend assets matched the build.

The deployed dashboard rendered Web search and Up HTTP in the table, and Web search / upstream HTTP in details, using synthetic API fixtures with no browser errors or warnings. Ordinary production requests succeeded after cutover; no real post-cutover search request had arrived at the verification snapshot. Legacy rows were not rewritten. Build inputs, the production adaptation patch, verification results, and rollback image identity are retained in the sibling `evidence/deployment` directory. No commit, push, public PR, or image publication was performed.

### Real production search verification

At the user's request, a real search for `site:openai.com OpenAI official website` was executed through Codex at 10:55:13 Europe/Stockholm on 2026-10-31. The correlated `/backend-api/codex/alpha/search` access log returned HTTP 200; the persisted row recorded success, `codex_control_alpha_search`, and upstream `http` with 1725 ms latency. The authenticated production dashboard, using live API data without mocks, showed Web search, Up HTTP, and OK. Its detail view showed Web search as the request kind and HTTP as the upstream transport; the visible request ID matched the database row. An earlier manual probe at 10:54:35 returned HTTP 400 because its test payload omitted the required `id` field; that test error row was retained. The complete sanitized result is in `evidence/deployment/real-search-verification.json` beside the worktree.
