"""Messaging transport state: dispatch evidence on communications + candidate replies.

Adds the transport columns the outbox bridge writes (``recipient``, ``provider``,
``provider_message_id``, ``send_attempts``, ``last_error``) and the
``candidate_replies`` table that stores inbound candidate mail exactly once per
provider message. Both carry tenant row-level security, mirroring
``db/tables.py``.

Revision ID: 0010_messaging_transport
Revises: 0009_offers
Create Date: 2026-09-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql
from hr_agents.tenancy import DEFAULT_TENANT_ID

revision: str = "0010_messaging_transport"
down_revision: str | None = "0009_offers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("candidate_communications", sa.Column("recipient", sa.String(length=320)))
    op.add_column("candidate_communications", sa.Column("provider", sa.String(length=64)))
    op.add_column(
        "candidate_communications", sa.Column("provider_message_id", sa.String(length=500))
    )
    op.add_column(
        "candidate_communications",
        sa.Column("send_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("candidate_communications", sa.Column("last_error", sa.Text()))

    op.create_table(
        "candidate_replies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "communication_id",
            sa.Uuid(),
            sa.ForeignKey("candidate_communications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="email"),
        sa.Column("sender", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_message_id", sa.String(length=500), nullable=True),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at",
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
        sa.UniqueConstraint("provider", "dedup_key", name="uq_candidate_replies_provider_dedup"),
    )
    op.create_index("ix_candidate_replies_candidate", "candidate_replies", ["candidate_id"])

    for statement in enable_tenant_rls_sql("candidate_replies"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("candidate_replies"):
        op.execute(statement)
    op.drop_index("ix_candidate_replies_candidate", table_name="candidate_replies")
    op.drop_table("candidate_replies")
    op.drop_column("candidate_communications", "last_error")
    op.drop_column("candidate_communications", "send_attempts")
    op.drop_column("candidate_communications", "provider_message_id")
    op.drop_column("candidate_communications", "provider")
    op.drop_column("candidate_communications", "recipient")
