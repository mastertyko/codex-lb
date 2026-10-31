# Checkpoint verification, 2026-10-31

This checkpoint preserves the observed production source. It is not a deployment
or a claim that all development gates pass. The captured file hashes and original
image digest are in [manifest.json](manifest.json).

## Verified content

| Boundary | Result |
| --- | --- |
| Application, migrations, scripts and registry | All 795 files match the running image byte for byte. |
| Dashboard | All 90 generated assets, including their complete file set, match after a frozen install and Node-based Vite build. |
| Native helper | The Linux ARM64 binary rebuilt with the Dockerfile's Rust 1.96.0 stage matches SHA-256 `447438c40d63579ac39883a06f82016d1928203358b7b7148eb24035c7c9371c`. |
| Python dependencies | All 93 installed runtime package versions match `uv.lock`; Brotli is pinned to the observed 1.2.1 version. |
| Schema | One head: `20260930_000000_add_pro_legacy_allowance`; topology checks pass. Fresh SQLite and PostgreSQL 18 upgrade, drift check and current-head checks pass. |
| Source lint and formatting | Ruff reports no findings; all 1,348 Python files pass its formatting check. |
| Checkpoint verifier | Eight CLI cases pass, covering valid files and changed, missing, extra, symlinked, asset, build-input and native content. |
| Focused backend regressions | 725 tests pass across request logs, transport, Pro allowance migration, cost accounting, Desktop credentials/predictions/retired Voice, native WebSocket framing, Responses input and the checkpoint verifier. |
| Search and warmup regressions | 20 tests pass in the proxy API, warmup and compact suites; 165 unrelated cases are deselected. |
| Retained WebSocket and routing regressions | 54 tests pass across idle loss, paused accounts, socket reuse, quota-first routing and consumption balancing. |
| Frontend | Lint, typecheck, build and all 1,711 tests in 181 files pass. |
| OpenSpec | All 67 canonical specifications and the checkpoint change pass strict validation with OpenSpec 1.11.0. |
| Preservation | A subsequent read confirms all 885 production source/asset files, the application image, both container start times and zero restart counts are unchanged. All 57 pre-existing worktrees retain their original heads, status and changed-file contents. |

## Existing test and typing limitations

The required `uv run pre-commit run local-ci --hook-stage manual --all-files`
was run to completion. It passes the frontend stages and stops at the architecture
check with two failures in the captured source: `streaming/mixin.py` has 1,102
lines against a 1,100-line limit, and HTTP-bridge quota rebalance imports a
WebSocket-domain module. The later full-CI stages were not reached. Ruff,
typecheck, migrations and the selected backend suites were run independently;
their results are reported here instead of implying the full gate passed.

The broader backend selection exposed six failing cases. They were reproduced
separately rather than treated as a successful full-suite run:

- `test_probe_route_omits_unsupported_output_limit`: the probe reports HTTP 400
  where the fixture expects 200.
- Four `test_dashboard_omits_fleet_pace_with_reported_unsupported_secondary_usage`
  cases: the captured implementation returns a weekly pace where the tests
  expect no pace.
- `test_dashboard_projections_ewma_tail_cap_matches_uncapped_history`: the query
  returns 1,008 rows where the test expects 82.

The diagnostic reruns produced 13 passing / 1 failing and 4 passing / 5 failing
cases respectively. The initial broader run was stopped for triage and is not
counted as completed verification. These results establish differences between
the preserved implementation and existing test expectations; they do not by
themselves establish the cause of a production incident.

`ty check` reports 91 diagnostics, largely involving test mocks and private
attributes; the retained WebSocket/routing suites still pass at runtime.
Runtime source is deliberately not rewritten to satisfy those
checks: doing so would create a different version. Obsolete tests importing the
removed Desktop Voice implementation were excluded; its current route-retirement
regressions are retained and pass.

## Provenance and privacy

The branch is based on the already published fork commit
`09a140fa9979a908e60acc97232367e0a08ef32c`. Runtime files are copied from the
observed image, not inferred from any single development branch. Frontend source
is paired with the dependency lock actually used for the successful rebuild;
the earlier deployment-source copy contained a stale frontend lock.

All prospective repository files were scanned with Gitleaks 8.30.1 and reviewed
for personal data, local paths and private infrastructure identifiers. The 13
initial scanner matches were reviewed as synthetic fixtures, public protocol
examples, prose or a type annotation. The final scan adds 162 matches in the
manifest; each is a verified public SHA-256 file/image fingerprint, not a
credential. No unclassified secret-scanner findings remain. A restored test fixture's project/user
references were replaced with neutral example data. Existing public upstream
author attribution remains unchanged.

Production credentials, environment values, account records, databases,
screenshots, raw test/deployment logs and local operational evidence are not part
of this checkpoint. Commit identity uses a public alias and GitHub noreply email.

Source and rebuilt binary/asset parity do not imply an identical full container
image: operating-system layers and the original overlay history are not
reconstructed. Local Python tests use 3.14.10; production reported 3.14.8.
Health inspection was read-only and skipped the drain probe, which can perform
housekeeping. No deployment, restart, production migration, PR or main-branch
update is part of this delivery.
