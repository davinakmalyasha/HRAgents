"""Point an evaluation's application at the applications table.

``evaluations.application_id`` could name anything. ``get_by_application``
reads evaluations keyed by that id, so an orphaned value is a lookup that
can never succeed. The pipeline worker validates the application before
registering, so no live write path creates one today -- this migration
makes the column itself hold the rule instead of relying on every future
caller remembering it.

``ON DELETE SET NULL``: an evaluation is a record of what happened, and it
outlives the application row it was about.

Revision ID: 0026_evaluation_application_fk
Revises: 0025_leave_document_fk
Create Date: 2026-10-18

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026_evaluation_application_fk"
down_revision: str | None = "0025_leave_document_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "fk_evaluations_application"


def upgrade() -> None:
    op.create_foreign_key(
        _NAME,
        "evaluations",
        "applications",
        ["application_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_NAME, "evaluations", type_="foreignkey")
