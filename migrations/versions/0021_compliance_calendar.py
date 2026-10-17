"""Create ``compliance_calendar_entries`` for operator-entered calendar dates.

The compliance calendar shows two kinds of due dates. Derived ones (probation
ends, contract expiries, document expiries) come from records that already
exist; statutory and policy dates the product must not invent need a home, and
it is this table. ``source_note`` is required so every operator date names
where it came from -- the same provenance rule rate tables live by.

Revision ID: 0021_compliance_calendar
Revises: 0020_optimistic_concurrency
Create Date: 2026-10-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql

revision: str = "0021_compliance_calendar"
down_revision: str | None = "0020_optimistic_concurrency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compliance_calendar_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("jurisdiction", sa.String(length=2), nullable=False, server_default="ID"),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_calendar_due_on", "compliance_calendar_entries", ["due_on"])
    op.create_index(
        "ix_compliance_calendar_entries_tenant", "compliance_calendar_entries", ["tenant_id"]
    )
    for statement in enable_tenant_rls_sql("compliance_calendar_entries"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("compliance_calendar_entries"):
        op.execute(statement)
    op.drop_index("ix_compliance_calendar_entries_tenant", table_name="compliance_calendar_entries")
    op.drop_index("ix_calendar_due_on", table_name="compliance_calendar_entries")
    op.drop_table("compliance_calendar_entries")
