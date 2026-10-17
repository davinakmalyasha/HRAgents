"""Point the growth rows at real employees.

``review_assignments``, ``review_summaries`` and ``goals`` named an employee
with nothing enforcing the reference; 0022 closed the cycle side of the same
tables. Unlike those, these needed a service change first: creation did no
employee lookup, so a foreign key on its own would have turned a mistyped id
into an integrity error at the database and a 500 at the API. ``GrowthService``
now resolves the employee at every creation path and answers a shaped 404; the
constraints land after that behaviour exists, which is why they are a separate
migration rather than part of 0022.

Revision ID: 0024_growth_employee_fks
Revises: 0023_check_constraints
Create Date: 2026-10-17

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_growth_employee_fks"
down_revision: str | None = "0023_check_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOREIGN_KEYS: tuple[tuple[str, str, str], ...] = (
    ("fk_review_assignments_employee", "review_assignments", "employee_id"),
    ("fk_review_summaries_employee", "review_summaries", "employee_id"),
    ("fk_goals_employee", "goals", "employee_id"),
)


def upgrade() -> None:
    for name, table, column in _FOREIGN_KEYS:
        op.create_foreign_key(name, table, "employees", [column], ["id"])


def downgrade() -> None:
    for name, table, _column in reversed(_FOREIGN_KEYS):
        op.drop_constraint(name, table, type_="foreignkey")
