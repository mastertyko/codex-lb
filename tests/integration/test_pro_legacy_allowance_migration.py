from __future__ import annotations

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from anyio import to_thread
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.migrate import _build_alembic_config, check_schema_drift, run_upgrade

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_legacy_allowance_migration_preserves_historical_rows_and_roundtrips(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'legacy-allowance.sqlite'}"
    parent = "20260918_000000_merge_scim_and_overflow_heads"
    revision = "20260930_000000_add_pro_legacy_allowance"
    config = _build_alembic_config(url)
    assert ScriptDirectory.from_config(config).get_heads() == [revision]
    await to_thread.run_sync(lambda: run_upgrade(url, parent, bootstrap_legacy=False))
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO accounts (id, email, plan_type, access_token_encrypted, refresh_token_encrypted, "
                    "id_token_encrypted, last_refresh, status, codex_installation_id) "
                    "VALUES ('historic', 'historic@example.com', 'pro', X'61', X'62', X'63', "
                    "'2026-09-01 00:00:00', 'active', 'historic-installation')"
                )
            )
        await to_thread.run_sync(lambda: run_upgrade(url, "head", bootstrap_legacy=False))
        async with engine.connect() as conn:
            assert (
                await conn.execute(text("SELECT pro_legacy_allowance FROM accounts WHERE id='historic'"))
            ).scalar_one() == 0
        assert await to_thread.run_sync(lambda: check_schema_drift(url)) == ()

        await to_thread.run_sync(lambda: command.downgrade(config, parent))
        async with engine.connect() as conn:
            columns = await conn.run_sync(lambda sync: inspect(sync).get_columns("accounts"))
            assert "pro_legacy_allowance" not in {column["name"] for column in columns}
        await to_thread.run_sync(lambda: run_upgrade(url, "head", bootstrap_legacy=False))
        async with engine.connect() as conn:
            assert (
                await conn.execute(text("SELECT pro_legacy_allowance FROM accounts WHERE id='historic'"))
            ).scalar_one() == 0
    finally:
        await engine.dispose()
