"""Tenancy: tenant_id on every table with PostgreSQL row-level security.

Backfills all existing rows to the default tenant, then enables ``FORCE`` RLS
with one policy per table (see ``hr_agents.db.rls``). An unset
``app.tenant_id`` session variable behaves as the default tenant.

Revision ID: 0006_tenancy
Revises: 0005_persistence
Create Date: 2026-09-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql
from hr_agents.tenancy import DEFAULT_TENANT_ID

revision: str = "0006_tenancy"
down_revision: str | None = "0005_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES: tuple[str, ...] = (
    "applications",
    "approvals",
    "audit_log",
    "breach_incidents",
    "candidate_documents",
    "candidates",
    "consent_records",
    "contracts",
    "conversations",
    "employee_documents",
    "employees",
    "erasure_requests",
    "evaluation_overrides",
    "evaluations",
    "feedback_reports",
    "goals",
    "jobs",
    "messages",
    "offboarding_assets",
    "offboarding_plans",
    "offboarding_templates",
    "org_units",
    "rate_tables",
    "retention_policies",
    "retention_records",
    "review_assignments",
    "review_cycles",
    "review_summaries",
    "schedule_proposals",
    "scheduling_availability",
    "tasks",
)


def upgrade() -> None:
    for table in _TENANT_TABLES:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.Uuid(),
                nullable=False,
                server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
            ),
        )
        for statement in enable_tenant_rls_sql(table):
            op.execute(statement)


def downgrade() -> None:
    for table in reversed(_TENANT_TABLES):
        for statement in disable_tenant_rls_sql(table):
            op.execute(statement)
        op.drop_column(table, "tenant_id")
