"""Add the cancellation columns to ``payroll_runs``.

``PayrollRun`` carried no ``cancelled_at``/``cancel_reason``, so a cancelled run
was a status with no why: the review packet showed "cancelled" and the reason
existed only in the audit chain, where nobody reading the packet would look. The
model now requires both together, and this migration brings the table into line
with what the model declares.

Revision ID: 0019_payroll_cancel_reason
Revises: 0018_tenant_indexes
Create Date: 2026-10-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_payroll_cancel_reason"
down_revision: str | None = "0018_tenant_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payroll_runs",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payroll_runs",
        sa.Column("cancel_reason", sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payroll_runs", "cancel_reason")
    op.drop_column("payroll_runs", "cancelled_at")
