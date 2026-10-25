"""Journal every purge attempt.

The handlers span stores without a shared transaction, so a purge cannot be made
atomic here. What it can be is recoverable and visible: a row is written before
a handler runs, finished on success or failure, and any `running` row left by a
crashed process is reconciled by the next sweep (done if the ledger says the
record was purged, failed-and-retried otherwise). Handlers are idempotent, which
is what makes the retry safe.

Revision ID: 0033_purge_jobs
Revises: 0032_llm_usage
Create Date: 2026-10-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql

revision: str = "0033_purge_jobs"
down_revision: str | None = "0032_llm_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_purge_jobs_record"


def upgrade() -> None:
    op.create_table(
        "purge_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_foreign_key(
        _FK, "purge_jobs", "retention_records", ["record_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_purge_jobs_tenant", "purge_jobs", ["tenant_id"])
    op.create_index("ix_purge_jobs_status", "purge_jobs", ["tenant_id", "status"])
    for statement in enable_tenant_rls_sql("purge_jobs"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("purge_jobs"):
        op.execute(statement)
    op.drop_index("ix_purge_jobs_status", table_name="purge_jobs")
    op.drop_index("ix_purge_jobs_tenant", table_name="purge_jobs")
    op.drop_constraint(_FK, "purge_jobs", type_="foreignkey")
    op.drop_table("purge_jobs")
