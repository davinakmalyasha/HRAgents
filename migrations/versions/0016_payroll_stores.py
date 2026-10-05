"""Persist payroll runs and their computed payslip lines.

``PayrollService`` held runs in a plain dict. Losing one is not losing a
convenience: ``compute()`` resolves the rate tables in force *for the period being
paid*, so re-running a March 2025 payroll after a newer decree was loaded produces
different figures from identical inputs and records the newer tables as the
provenance. The first computation is the only correct one, and it is gone.

Two tables, with money in ``Numeric(18, 2)`` rather than a JSON document. A payslip
is the one artefact here that an employee reconciles line by line against a bank
transfer, so the amounts have to be comparable in SQL; a JSON blob would put every
reconciliation query in Python, which is where the float rounding bugs came from.

``payroll_lines`` is unique on (run_id, employee_id) because ``PayrollLine`` carries
no id of its own -- the pair is the identity, and the database enforces it rather
than the adapter assuming it.

``payroll_runs`` has no cancelled_at / cancel_reason column: ``PayrollRun`` does not
carry them. The cancellation reason is written to the tamper-evident audit chain and
nowhere else, and it is not invented here.

Revision ID: 0016_payroll_stores
Revises: 0015_leave_stores
Create Date: 2026-10-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql
from hr_agents.tenancy import DEFAULT_TENANT_ID

revision: str = "0016_payroll_stores"
down_revision: str | None = "0015_leave_stores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())

# Every money column on a payslip line. The names are the `models.money.Money` field
# names, so the adapter maps them positionally; two places means two places to keep
# in step, and `PayrollLine.check_invariants` is the guard that catches a drift --
# a line whose components do not add to its total cannot be written or read back.
_AMOUNTS = (
    "base_salary",
    "allowances",
    "overtime_pay",
    "bonus",
    "gross",
    "bpjs_kesehatan_employee",
    "bpjs_jht_employee",
    "bpjs_jp_employee",
    "pph21",
    "other_deductions",
    "total_deductions",
    "net",
    "bpjs_kesehatan_employer",
    "bpjs_jht_employer",
    "bpjs_jp_employer",
    "bpjs_jkk_employer",
    "bpjs_jkm_employer",
    "employer_cost",
)


def upgrade() -> None:
    op.create_table(
        "payroll_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("inputs", JSONB, nullable=False),
        sa.Column("anomalies", JSONB, nullable=False),
        sa.Column("rate_table_ids", JSONB, nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("signed_off_by", sa.String(length=200), nullable=True),
        sa.Column("signed_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_payroll_runs_tenant", "payroll_runs", ["tenant_id"])
    # `_previous_run` looks for the most recent earlier period of the same kind.
    op.create_index(
        "ix_payroll_runs_tenant_period",
        "payroll_runs",
        ["tenant_id", "period_year", "period_month"],
    )
    op.create_index("ix_payroll_runs_tenant_approval", "payroll_runs", ["tenant_id", "approval_id"])

    op.create_table(
        "payroll_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("employee_name", sa.String(length=200), nullable=False),
        *(sa.Column(name, sa.Numeric(18, 2), nullable=False) for name in _AMOUNTS),
        sa.Column("thr_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", JSONB, nullable=False),
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
        sa.UniqueConstraint("run_id", "employee_id", name="uq_payroll_lines_run_employee"),
    )
    op.create_index("ix_payroll_lines_tenant", "payroll_lines", ["tenant_id"])
    op.create_index("ix_payroll_lines_tenant_run", "payroll_lines", ["tenant_id", "run_id"])
    op.create_index(
        "ix_payroll_lines_tenant_employee", "payroll_lines", ["tenant_id", "employee_id"]
    )

    for table in ("payroll_runs", "payroll_lines"):
        for statement in enable_tenant_rls_sql(table):
            op.execute(statement)


def downgrade() -> None:
    for table in ("payroll_lines", "payroll_runs"):
        for statement in disable_tenant_rls_sql(table):
            op.execute(statement)
    op.drop_index("ix_payroll_lines_tenant_employee", table_name="payroll_lines")
    op.drop_index("ix_payroll_lines_tenant_run", table_name="payroll_lines")
    op.drop_index("ix_payroll_lines_tenant", table_name="payroll_lines")
    op.drop_table("payroll_lines")
    op.drop_index("ix_payroll_runs_tenant_approval", table_name="payroll_runs")
    op.drop_index("ix_payroll_runs_tenant_period", table_name="payroll_runs")
    op.drop_index("ix_payroll_runs_tenant", table_name="payroll_runs")
    op.drop_table("payroll_runs")
