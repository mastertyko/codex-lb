from __future__ import annotations

import asyncio
import gc
import logging
import os
import warnings

import anyio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.auth import desktop_oauth
from app.core.auth.desktop_identity import DesktopIdentityPrincipal
from app.core.auth.desktop_oauth import DesktopOAuthAdmission, DesktopOAuthCredentials
from app.core.config.settings import DesktopOAuthGrant, get_settings
from app.core.utils.time import utcnow
from app.db import session as session_module
from app.db.models import Account, AccountStatus, ApiKey
from app.dependencies import _proxy_repo_context
from app.modules.api_keys.service import ApiKeyData
from app.modules.proxy import desktop_predictions as predictions
from app.modules.proxy.service import ProxyService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_mode", ["anyio", "asyncio"])
@pytest.mark.parametrize("phase", ["owner_lookup", "owner_recheck", "grant_key_read"])
async def test_prediction_cancellation_returns_postgres_checkout_before_stopping(
    db_setup, monkeypatch, caplog, cancel_mode, phase
):
    url = os.environ.get("CODEX_LB_TEST_DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("requires CODEX_LB_TEST_DATABASE_URL=postgresql+asyncpg://...")

    # Exercise a real pooled checkout: the general test engine uses NullPool,
    # which cannot reproduce cancellation during PostgreSQL's pre-ping.
    engine = create_async_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "_background_session_factory", factory)
    async with factory() as session:
        session.add(
            Account(
                id="cancel-owner",
                chatgpt_user_id="cancel-user",
                chatgpt_account_id="cancel-workspace",
                email="cancel@example.invalid",
                plan_type="pro",
                status=AccountStatus.ACTIVE,
                last_refresh=utcnow(),
                access_token_encrypted=b"test-access",
                refresh_token_encrypted=b"test-refresh",
                id_token_encrypted=b"test-id",
            )
        )
        session.add(ApiKey(id="cancel-key", name="cancel-test", key_hash="cancel-hash", key_prefix="test"))
        await session.commit()

    ping_started = anyio.Event()
    finish_ping = anyio.Event()
    finished = anyio.Event()
    scopes = []
    tasks = []
    lease_calls = []
    cancellations = []
    completed = []
    ping_count = 0

    async def ping(connection):
        nonlocal ping_count
        ping_count += 1
        # The recheck reads the grant first, then checks out again for the
        # account ownership query. Target that second checkout independently.
        target_ping = 2 if phase == "owner_recheck" else 1
        if ping_count == target_ping:
            ping_started.set()
            await finish_ping.wait()
        await connection.driver_connection.execute("SELECT 1")
        return True

    monkeypatch.setattr(engine.sync_engine.dialect, "do_ping", lambda connection: connection.await_(ping(connection)))
    service = ProxyService(_proxy_repo_context)

    async def acquire_lease(*args, **kwargs):
        lease_calls.append(True)
        raise AssertionError("a cancelled prediction must not acquire an account lease")

    monkeypatch.setattr(service._load_balancer, "acquire_account_lease", acquire_lease)
    admission = DesktopOAuthAdmission(
        credentials=DesktopOAuthCredentials("unused", "cancel-workspace"),
        principal=DesktopIdentityPrincipal("cancel-user", "cancel-workspace"),
        api_key=ApiKeyData(
            id="cancel-key",
            name="cancel-test",
            key_prefix="test",
            allowed_models=None,
            enforced_model=None,
            enforced_reasoning_effort=None,
            enforced_service_tier=None,
            expires_at=None,
            is_active=True,
            created_at=utcnow(),
            last_used_at=None,
        ),
    )
    monkeypatch.setattr(
        get_settings(),
        "desktop_oauth_grants",
        [DesktopOAuthGrant(user_id="cancel-user", workspace_id="cancel-workspace", api_key_id="cancel-key")],
    )
    monkeypatch.setattr(predictions, "parse_desktop_identity_principal", lambda *args: admission.principal)

    async def lookup():
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            tasks.append(asyncio.current_task())
            try:
                if phase == "owner_lookup":
                    async with predictions._owner(service, admission):
                        pytest.fail("cancelled prediction reached dispatch")
                elif phase == "owner_recheck":
                    await predictions._recheck_owner(service, admission, "cancel-owner")
                else:
                    await desktop_oauth.recheck_desktop_grant(admission.principal, "cancel-key")
                completed.append(True)
            except asyncio.CancelledError:
                cancellations.append(True)
                raise
            finally:
                finished.set()

    try:
        with warnings.catch_warnings(record=True) as caught, caplog.at_level(logging.ERROR, logger="sqlalchemy.pool"):
            with anyio.fail_after(5):
                async with anyio.create_task_group() as group:
                    group.start_soon(lookup)
                    await ping_started.wait()
                    if cancel_mode == "anyio":
                        scopes[0].cancel()
                    else:
                        tasks[0].cancel()
                        await anyio.sleep(0)
                        tasks[0].cancel()
                    await anyio.sleep(0)
                    assert not finished.is_set(), "cancellation must wait for its owned database operation"
                    finish_ping.set()
                    await finished.wait()
            gc.collect()
            await asyncio.sleep(0)

        assert cancellations == [True]
        assert completed == []
        assert lease_calls == []
        assert engine.pool.checkedout() == 0
        assert not any("non-checked-in" in str(item.message) for item in caught)
        assert not any("Exception terminating connection" in record.message for record in caplog.records)
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
    finally:
        await engine.dispose()
