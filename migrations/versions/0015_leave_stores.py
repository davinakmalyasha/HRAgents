"""Persist leave requests, policies, balance adjustments and the holiday calendar.

``LeaveService`` held all four in plain dicts and sets, so a restart lost them. The
loss is not uniform: a lost request is visible (the employee's approved leave
vanishes from their list), but a lost balance adjustment silently overstates the
balance and a lost holiday calendar silently makes ``working_days`` count a public
holiday as a working day. Nothing reported either.

This migration adds the persistence primitives ``LeaveService`` now exposes
(``_load_request``/``_iter_requests``/``_save_request``, the policy equivalents, the
adjustment pair and the calendar pair) so ``DbLeaveService`` can implement only
those. The balance, overlap and lifecycle rules stay in the service class.

``leave_adjustments`` is keyed by (employee, leave type, year) rather than a
synthetic id, because that triple is the identity: a second adjustment to the same
employee, type and year must accumulate onto the same row.

Revision ID: 0015_leave_stores
Revises: 0014_workspace_stores
Create Date: 2026-10-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql
from hr_agents.tenancy import DEFAULT_TENANT_ID

revision: str = "0015_leave_stores"
down_revision: str | None = "0014_workspace_stores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("leave_type", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
    )
    op.create_index("ix_leave_requests_tenant", "leave_requests", ["tenant_id"])
    op.create_index(
        "ix_leave_requests_tenant_employee", "leave_requests", ["tenant_id", "employee_id"]
    )
    # `apply_decision` resolves the request that owns an approval id.
    op.create_index(
        "ix_leave_requests_tenant_approval", "leave_requests", ["tenant_id", "approval_id"]
    )

    op.create_table(
        "leave_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("leave_type", sa.String(length=32), nullable=False),
        sa.Column("policy", JSONB, nullable=False),
        *_timestamps(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
    )
    op.create_index("ix_leave_policies_tenant", "leave_policies", ["tenant_id"])

    op.create_table(
        "leave_adjustments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("leave_type", sa.String(length=32), nullable=False),
        sa.Column("target_year", sa.Integer(), nullable=False),
        sa.Column("days", sa.Float(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
    )
    op.create_index("ix_leave_adjustments_tenant", "leave_adjustments", ["tenant_id"])

    op.create_table(
        "leave_holidays",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text(f"'{DEFAULT_TENANT_ID}'"),
        ),
    )
    op.create_index("ix_leave_holidays_tenant", "leave_holidays", ["tenant_id"])
    op.create_index("ix_leave_holidays_tenant_day", "leave_holidays", ["tenant_id", "day"])

    for table in (
        "leave_requests",
        "leave_policies",
        "leave_adjustments",
        "leave_holidays",
    ):
        for statement in enable_tenant_rls_sql(table):
            op.execute(statement)


def downgrade() -> None:
    for table in (
        "leave_holidays",
        "leave_adjustments",
        "leave_policies",
        "leave_requests",
    ):
        for statement in disable_tenant_rls_sql(table):
            op.execute(statement)
    op.drop_index("ix_leave_holidays_tenant_day", table_name="leave_holidays")
    op.drop_index("ix_leave_holidays_tenant", table_name="leave_holidays")
    op.drop_table("leave_holidays")
    op.drop_index("ix_leave_adjustments_tenant", table_name="leave_adjustments")
    op.drop_table("leave_adjustments")
    op.drop_index("ix_leave_policies_tenant", table_name="leave_policies")
    op.drop_table("leave_policies")
    op.drop_index("ix_leave_requests_tenant_approval", table_name="leave_requests")
    op.drop_index("ix_leave_requests_tenant_employee", table_name="leave_requests")
    op.drop_index("ix_leave_requests_tenant", table_name="leave_requests")
    op.drop_table("leave_requests")
