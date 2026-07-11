from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, ApiKey
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.request_logs.repository import RequestLogsRepository

pytestmark = pytest.mark.integration

EXPECTED_ACTIVITY_FIELDS = {
    "activity",
    "stale",
    "source",
    "sourceStatus",
    "generatedAt",
    "since",
    "windowSeconds",
    "requestCount",
    "errorCount",
    "inputTokens",
    "outputTokens",
    "cachedInputTokens",
    "costUsd",
}


def _make_account(account_id: str, email: str) -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        email=email,
        plan_type="plus",
        access_token_encrypted=encryptor.encrypt("access"),
        refresh_token_encrypted=encryptor.encrypt("refresh"),
        id_token_encrypted=encryptor.encrypt("id"),
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
    )


@pytest.mark.asyncio
async def test_activity_state_allows_credentialless_polling_and_reports_idle(async_client, db_setup):
    del db_setup

    response = await async_client.get("/api/activity/state")

    assert "authorization" not in response.request.headers
    assert "cookie" not in response.request.headers
    assert response.status_code == 200
    body = response.json()
    assert set(body) == EXPECTED_ACTIVITY_FIELDS
    assert body["activity"] == 0.0
    assert body["stale"] is False
    assert body["source"] == "codex-lb"
    assert body["sourceStatus"] == "ok"
    assert body["windowSeconds"] == 120
    assert body["requestCount"] == 0
    assert body["errorCount"] == 0
    assert body["inputTokens"] == 0
    assert body["outputTokens"] == 0
    assert body["cachedInputTokens"] == 0
    assert body["costUsd"] == 0.0


@pytest.mark.asyncio
async def test_activity_state_reports_recent_aggregate_without_sensitive_fields(async_client, db_setup):
    del db_setup
    async with SessionLocal() as session:
        accounts_repository = AccountsRepository(session)
        logs_repository = RequestLogsRepository(session)
        await accounts_repository.upsert(_make_account("acc_activity_secret", "activity-secret@example.com"))
        session.add(
            ApiKey(
                id="key_activity_secret",
                name="Activity Secret Key",
                key_hash="hash_activity_secret",
                key_prefix="sk-activity-secret",
            )
        )
        await session.commit()

        now = utcnow()
        await logs_repository.add_log(
            account_id="acc_activity_secret",
            request_id="req_activity_success_secret",
            model="gpt-5.1-secret",
            input_tokens=100,
            output_tokens=200,
            cached_input_tokens=30,
            latency_ms=1200,
            status="success",
            error_code=None,
            requested_at=now - timedelta(seconds=10),
            api_key_id="key_activity_secret",
            session_id="sess_activity_secret",
            useragent="secret-user-agent/1.0",
        )
        await logs_repository.add_log(
            account_id="acc_activity_secret",
            request_id="req_activity_error_secret",
            model="gpt-5.1-secret",
            input_tokens=40,
            output_tokens=5,
            cached_input_tokens=3,
            latency_ms=300,
            status="error",
            error_code="activity_secret_error_code",
            error_message="Activity secret error message",
            requested_at=now - timedelta(seconds=5),
        )
        await logs_repository.add_log(
            account_id="acc_activity_secret",
            request_id="req_activity_warmup_secret",
            model="gpt-5.1-secret",
            input_tokens=999,
            output_tokens=999,
            latency_ms=10,
            status="success",
            error_code=None,
            requested_at=now,
            request_kind="warmup",
        )
        await logs_repository.add_log(
            account_id="acc_activity_secret",
            request_id="req_activity_old_secret",
            model="gpt-5.1-secret",
            input_tokens=888,
            output_tokens=888,
            latency_ms=10,
            status="success",
            error_code=None,
            requested_at=now - timedelta(hours=2),
        )

    response = await async_client.get("/api/activity/state?windowSeconds=120")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == EXPECTED_ACTIVITY_FIELDS
    assert 0.0 < body["activity"] <= 1.0
    assert body["stale"] is False
    assert body["windowSeconds"] == 120
    assert body["requestCount"] == 2
    assert body["errorCount"] == 1
    assert body["inputTokens"] == 140
    assert body["outputTokens"] == 205
    assert body["cachedInputTokens"] == 33
    assert body["costUsd"] >= 0.0

    forbidden_fragments = [
        "acc_activity_secret",
        "activity-secret@example.com",
        "key_activity_secret",
        "Activity Secret Key",
        "sk-activity-secret",
        "req_activity_success_secret",
        "req_activity_error_secret",
        "req_activity_warmup_secret",
        "req_activity_old_secret",
        "sess_activity_secret",
        "gpt-5.1-secret",
        "secret-user-agent",
        "activity_secret_error_code",
        "Activity secret error message",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("requested", "expected"), [(-1, 10), (999_999, 3600)])
async def test_activity_state_clamps_query_window(async_client, db_setup, requested, expected):
    del db_setup

    response = await async_client.get(f"/api/activity/state?windowSeconds={requested}")

    assert response.status_code == 200
    assert response.json()["windowSeconds"] == expected
