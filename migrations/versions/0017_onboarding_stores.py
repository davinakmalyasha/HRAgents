"""Persist onboarding checklist templates and per-hire plans.

``OnboardingService`` held both in plain dicts. The loss that matters is a *waived*
step: a hire whose document check HR had already waived, with a recorded reason,
comes back as not-waived after a restart, and the next person to open the plan sees a
blocker that was already resolved. The waiver reason is the record.

``onboarding_plans.completed_at`` is indexed because ``active_plans`` -- everything
still in flight -- is the view every onboarding dashboard reads, and it was a full
read of the tenant's plans.

Revision ID: 0017_onboarding_stores
Revises: 0016_payroll_stores
Create Date: 2026-10-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql
from hr_agents.tenancy import DEFAULT_TENANT_ID

revision: str = "0017_onboarding_stores"
down_revision: str | None = "0016_payroll_stores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "onboarding_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("applies_to_contract_types", JSONB, nullable=False),
        sa.Column("applies_to_roles", JSONB, nullable=False),
        sa.Column("steps", JSONB, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
    op.create_index("ix_onboarding_templates_tenant", "onboarding_templates", ["tenant_id"])
    op.create_index(
        "ix_onboarding_templates_tenant_active",
        "onboarding_templates",
        ["tenant_id", "active"],
    )

    op.create_table(
        "onboarding_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("template_name", sa.Text(), nullable=False),
        sa.Column("template_version_hash", sa.String(length=64), nullable=False),
        sa.Column("steps", JSONB, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
    )
    op.create_index("ix_onboarding_plans_tenant", "onboarding_plans", ["tenant_id"])
    op.create_index(
        "ix_onboarding_plans_tenant_employee", "onboarding_plans", ["tenant_id", "employee_id"]
    )
    op.create_index(
        "ix_onboarding_plans_tenant_inflight",
        "onboarding_plans",
        ["tenant_id", "completed_at", "started_at"],
    )

    for table in ("onboarding_templates", "onboarding_plans"):
        for statement in enable_tenant_rls_sql(table):
            op.execute(statement)


def downgrade() -> None:
    for table in ("onboarding_plans", "onboarding_templates"):
        for statement in disable_tenant_rls_sql(table):
            op.execute(statement)
    op.drop_index("ix_onboarding_plans_tenant_inflight", table_name="onboarding_plans")
    op.drop_index("ix_onboarding_plans_tenant_employee", table_name="onboarding_plans")
    op.drop_index("ix_onboarding_plans_tenant", table_name="onboarding_plans")
    op.drop_table("onboarding_plans")
    op.drop_index("ix_onboarding_templates_tenant_active", table_name="onboarding_templates")
    op.drop_index("ix_onboarding_templates_tenant", table_name="onboarding_templates")
    op.drop_table("onboarding_templates")
