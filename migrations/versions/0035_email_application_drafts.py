"""Email application drafts for CVs arriving in the hiring mailbox.

Tenant-scoped like the reply table: a draft names a sender and stores their
documents, so it is personal data from the first byte. Deduplication is a
unique provider/dedup pair, and the status index serves the pending queue.

Revision ID: 0035_email_application_drafts
Revises: 0034_mcp_servers
Create Date: 2026-10-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql

revision: str = "0035_email_application_drafts"
down_revision: str | None = "0034_mcp_servers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "email_application_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_message_id", sa.String(length=500), nullable=True),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column("sender", sa.String(length=320), nullable=False),
        sa.Column("sender_name", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("subject", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachment_names", JSONB, nullable=False, server_default="[]"),
        sa.Column("document_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("refused_attachments", JSONB, nullable=False, server_default="[]"),
        sa.Column("suggested_job_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("discard_reason", sa.String(length=1000), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["suggested_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "provider", "dedup_key", name="uq_email_application_drafts_provider_dedup"
        ),
    )
    op.create_index("ix_email_application_drafts_tenant", "email_application_drafts", ["tenant_id"])
    op.create_index(
        "ix_email_application_drafts_status",
        "email_application_drafts",
        ["tenant_id", "status"],
    )
    for statement in enable_tenant_rls_sql("email_application_drafts"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("email_application_drafts"):
        op.execute(statement)
    op.drop_index("ix_email_application_drafts_status", table_name="email_application_drafts")
    op.drop_index("ix_email_application_drafts_tenant", table_name="email_application_drafts")
    op.drop_table("email_application_drafts")
