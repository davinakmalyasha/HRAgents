"""Link a re-run to the reviewed payroll run it replaces.

A computed run is the record a reviewer read. Recomputing in place rewrote its
figures and rate-table provenance after that review, so the audit trail showed a
run nobody had actually seen. A re-run is now a new row; ``supersedes_id`` names
the reviewed run it replaces, and the old row becomes terminal ``superseded``
rather than losing its numbers. The self-reference is nullable because most runs
are not re-runs.

Revision ID: 0028_payroll_supersedes
Revises: 0027_rubric_versions
Create Date: 2026-10-19

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_payroll_supersedes"
down_revision: str | None = "0027_rubric_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "fk_payroll_runs_supersedes"


def upgrade() -> None:
    op.add_column("payroll_runs", sa.Column("supersedes_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        _NAME,
        "payroll_runs",
        "payroll_runs",
        ["supersedes_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(_NAME, "payroll_runs", type_="foreignkey")
    op.drop_column("payroll_runs", "supersedes_id")
