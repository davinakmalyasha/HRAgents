"""Store Web Push subscriptions.

A subscription is a browser endpoint plus the keys the browser generated. The
row belongs to one actor; ``role`` is a snapshot used to select approval pings
and the sender re-checks it against the configured principals, so a revoked key
stops receiving them even though the row remains. The endpoint is unique per
actor: re-subscribing the same browser refreshes the keys instead of piling up
dead rows.

Revision ID: 0029_push_subscriptions
Revises: 0028_payroll_supersedes
Create Date: 2026-10-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql

revision: str = "0029_push_subscriptions"
down_revision: str | None = "0028_payroll_supersedes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=False),
        sa.Column("p256dh", sa.String(length=500), nullable=False),
        sa.Column("auth", sa.String(length=200), nullable=False),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "actor_id", "endpoint", name="uq_push_subscriptions_actor_endpoint"
        ),
    )
    op.create_index("ix_push_subscriptions_tenant", "push_subscriptions", ["tenant_id"])
    for statement in enable_tenant_rls_sql("push_subscriptions"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("push_subscriptions"):
        op.execute(statement)
    op.drop_index("ix_push_subscriptions_tenant", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
