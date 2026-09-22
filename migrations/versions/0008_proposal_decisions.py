"""Proposal decisions: supersede chain and named-human decision trail.

Adds ``supersedes_id``, ``decided_by``, and ``decided_at`` to
``schedule_proposals``; the ``status`` column already exists and now carries
the full proposal lifecycle (pending approval → confirmed/cancelled/superseded).

Revision ID: 0008_proposal_decisions
Revises: 0007_candidate_communications
Create Date: 2026-09-22

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_proposal_decisions"
down_revision: str | None = "0007_candidate_communications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("schedule_proposals", sa.Column("supersedes_id", sa.Uuid(), nullable=True))
    op.add_column(
        "schedule_proposals", sa.Column("decided_by", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "schedule_proposals",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schedule_proposals", "decided_at")
    op.drop_column("schedule_proposals", "decided_by")
    op.drop_column("schedule_proposals", "supersedes_id")
