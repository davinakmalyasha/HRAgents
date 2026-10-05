"""Durable Ask HR transcripts and handoff queues, plus the first tenant indexes.

``ConversationStore`` and ``WorkspaceRequestStore`` already exposed persistence
primitives, but nothing implemented them: both held their state in a plain dict
behind the memory backend, so a container restart or a second replica emptied them.
An answer the employee had already been given could not be shown again, and a
cross-workspace handoff vanished mid-workflow.

This is also the first migration to index ``tenant_id``. Row-level security filters
*every* query by tenant, and no table in the schema had an index on that column --
so the isolation layer was a sequential scan of the whole table on every read, and
the security mechanism set the performance floor for the entire database. The two
new tables lead with it; the 35 existing tables are indexed separately.

Revision ID: 0014_workspace_stores
Revises: 0013_evaluation_lookup_indexes
Create Date: 2026-10-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql
from hr_agents.tenancy import DEFAULT_TENANT_ID

revision: str = "0014_workspace_stores"
down_revision: str | None = "0013_evaluation_lookup_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace", sa.String(length=64), nullable=False),
        sa.Column("owner", sa.String(length=200), nullable=False),
        sa.Column("turns", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
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
    # Tenant-leading: RLS filters on tenant_id, so the index the planner can use for
    # a tenant-scoped read has to start there.
    op.create_index("ix_chat_conversations_tenant", "chat_conversations", ["tenant_id"])
    op.create_index(
        "ix_chat_conversations_tenant_owner",
        "chat_conversations",
        ["tenant_id", "owner"],
    )

    op.create_table(
        "workspace_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_workspace", sa.String(length=64), nullable=False),
        sa.Column("target_workspace", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
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
    op.create_index("ix_workspace_requests_tenant", "workspace_requests", ["tenant_id"])
    # `HandoffService.open_for` reads one workspace's open queue.
    op.create_index(
        "ix_workspace_requests_tenant_target_status",
        "workspace_requests",
        ["tenant_id", "target_workspace", "status"],
    )

    for table in ("chat_conversations", "workspace_requests"):
        for statement in enable_tenant_rls_sql(table):
            op.execute(statement)


def downgrade() -> None:
    for table in ("workspace_requests", "chat_conversations"):
        for statement in disable_tenant_rls_sql(table):
            op.execute(statement)
    op.drop_index("ix_workspace_requests_tenant_target_status", table_name="workspace_requests")
    op.drop_index("ix_workspace_requests_tenant", table_name="workspace_requests")
    op.drop_table("workspace_requests")
    op.drop_index("ix_chat_conversations_tenant_owner", table_name="chat_conversations")
    op.drop_index("ix_chat_conversations_tenant", table_name="chat_conversations")
    op.drop_table("chat_conversations")
