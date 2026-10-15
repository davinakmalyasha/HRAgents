"""Add the optimistic-concurrency ``version`` column to every tenant-scoped table.

`save_model` now compares the version a caller read against the version in the
row and refuses to overwrite a newer state. Without the column that check has
nothing to compare, so this migration is the other half of the guard: two
concurrent `complete_step` calls lose one another's change today, and a mid-loop
erasure can half-finish with nobody told.

The column is enumerated from the live database rather than a hand-written list,
the same reasoning as `0018`: a hand-written list is forty-five chances to miss
one, and the tables are discoverable.

Revision ID: 0020_optimistic_concurrency
Revises: 0019_payroll_cancel_reason
Create Date: 2026-10-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_optimistic_concurrency"
down_revision: str | None = "0019_payroll_cancel_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_tables(*, with_version: bool) -> list[str]:
    """Tenant-scoped tables whose version column is (not) there yet, sorted."""
    inspector = sa.inspect(op.get_bind())
    tables: list[str] = []
    for table in sorted(inspector.get_table_names()):
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "tenant_id" in columns and ("version" in columns) is with_version:
            tables.append(table)
    return tables


def upgrade() -> None:
    for table in _tenant_tables(with_version=False):
        op.add_column(
            table,
            sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for table in _tenant_tables(with_version=True):
        op.drop_column(table, "version")
