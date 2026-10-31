"""Preserve the effective rate card for newly priced subscription requests."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_190000_add_request_pricing_basis"
down_revision = "20260930_000000_add_pro_legacy_allowance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing totals remain authoritative; historical unit prices are unknown.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("request_logs")}
    if "pricing_basis_json" not in columns:
        op.add_column("request_logs", sa.Column("pricing_basis_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("request_logs", "pricing_basis_json")
