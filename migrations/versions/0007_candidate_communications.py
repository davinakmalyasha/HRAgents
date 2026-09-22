"""Candidate communications: the gated rejection/offer outbox.

Adds ``candidate_communications`` — candidate-facing messages queued only
behind a named human, dispatched outside the system — and enables the tenant
row-level security policy on it.

Revision ID: 0007_candidate_communications
Revises: 0006_tenancy
Create Date: 2026-09-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql
from hr_agents.tenancy import DEFAULT_TENANT_ID

revision: str = "0007_candidate_communications"
down_revision: str | None = "0006_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_communications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "evaluation_id",
            sa.Uuid(),
            sa.ForeignKey("evaluations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("approved_by", sa.String(length=200), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_by", sa.String(length=200), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
    )
    op.create_index(
        "ix_candidate_communications_candidate",
        "candidate_communications",
        ["candidate_id"],
    )
    for statement in enable_tenant_rls_sql("candidate_communications"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("candidate_communications"):
        op.execute(statement)
    op.drop_index("ix_candidate_communications_candidate", table_name="candidate_communications")
    op.drop_table("candidate_communications")
