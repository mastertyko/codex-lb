"""Persist explicit legacy Pro allowance selection, defaulting existing rows off."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_000000_add_pro_legacy_allowance"
down_revision = "20260927_190000_add_cache_write_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("pro_legacy_allowance", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("accounts", "pro_legacy_allowance")
