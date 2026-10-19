"""Point a leave request's supporting document at the vault.

``leave_requests.document_id`` accepted anything: any UUID, from any
employee, could be stored, and the policy gate only checked that *some* id
was present when the leave type required one. The document can only be an
``employee_documents`` row belonging to the requesting employee, which
``LeaveService.request`` now checks, and this migration adds the foreign key
that holds every other writer to the same rule.

``ON DELETE SET NULL`` because retention purges delete documents: the request
outlives the file it cited, with the reference emptied, instead of blocking
the purge or dangling.

Revision ID: 0025_leave_document_fk
Revises: 0024_growth_employee_fks
Create Date: 2026-10-18

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025_leave_document_fk"
down_revision: str | None = "0024_growth_employee_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "fk_leave_requests_document"


def upgrade() -> None:
    op.create_foreign_key(
        _NAME,
        "leave_requests",
        "employee_documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_NAME, "leave_requests", type_="foreignkey")
