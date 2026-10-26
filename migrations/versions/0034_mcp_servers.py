"""Dashboard-managed MCP server configurations.

Install-wide, not tenant-scoped: MCP tools live in one process-wide tool
registry, so pretending the rows were tenant-isolated would be a promise the
runtime cannot keep. Access is admin-only at the API.

Revision ID: 0034_mcp_servers
Revises: 0033_purge_jobs
Create Date: 2026-10-27

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_mcp_servers"
down_revision: str | None = "0033_purge_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("name", sa.String(length=40), primary_key=True),
        sa.Column("config", JSONB, nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mcp_servers")
