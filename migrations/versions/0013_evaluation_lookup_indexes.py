"""Index the evaluation lookups the candidate-facing paths perform.

``EvaluationService.get_by_candidate`` and ``get_by_application`` used to scan
every evaluation the process had loaded. Five call sites reach them -- the
rejection, offer and scheduling paths all start there -- so a candidate
interaction cost the size of the whole pipeline.

``ix_evaluations_candidate_job`` already leads with ``candidate_id``, so the
candidate lookup only needed to use it. ``application_id`` had no index at all,
which turned every ``get_by_application`` into a sequential scan.

Revision ID: 0013_evaluation_lookup_indexes
Revises: 0012_messaging_indexes
Create Date: 2026-10-02

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_evaluation_lookup_indexes"
down_revision: str | None = "0012_messaging_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_evaluations_application",
        "evaluations",
        ["application_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_evaluations_application", table_name="evaluations")
