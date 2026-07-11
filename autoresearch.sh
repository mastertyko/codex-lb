#!/usr/bin/env bash
set -euo pipefail

export PYTHONHASHSEED=0
export LC_ALL=C
export TZ=UTC
export CODEX_LB_DATABASE_URL="sqlite+aiosqlite:///:memory:"
export CODEX_LB_UPSTREAM_BASE_URL="https://example.invalid/backend-api"
export CODEX_LB_USAGE_REFRESH_ENABLED=false
export CODEX_LB_MODEL_REGISTRY_ENABLED=false
export CODEX_LB_STICKY_SESSION_CLEANUP_ENABLED=false
export CODEX_LB_HTTP_RESPONSES_SESSION_BRIDGE_ENABLED=false
export CODEX_LB_QUOTA_PLANNER_SCHEDULER_ENABLED=false

exec .venv/bin/python scripts/benchmark_hot_paths.py
