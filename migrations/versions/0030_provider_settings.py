"""Store operator-chosen provider configuration, encrypted.

A capability has at most one stored selection. The config is a Fernet token,
not a JSON column: it holds API keys, and a backup, a replica or a support dump
must not hand them over. The key lives in the environment, never in this table.

Revision ID: 0030_provider_settings
Revises: 0029_push_subscriptions
Create Date: 2026-10-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql

revision: str = "0030_provider_settings"
down_revision: str | None = "0029_push_subscriptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("config_sealed", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "capability", name="uq_provider_settings_capability"),
    )
    op.create_index("ix_provider_settings_tenant", "provider_settings", ["tenant_id"])
    for statement in enable_tenant_rls_sql("provider_settings"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("provider_settings"):
        op.execute(statement)
    op.drop_index("ix_provider_settings_tenant", table_name="provider_settings")
    op.drop_table("provider_settings")
