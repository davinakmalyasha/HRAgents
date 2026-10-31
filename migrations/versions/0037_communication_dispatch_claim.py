"""Lease columns on candidate_communications so one dispatcher sends a message.

Two overlapping ``run_messaging --send`` processes could both list the same
queued row, both call the transport, and the candidate received the message
twice. The row now carries a short lease the sender claims before handing
anything to the transport; the second process loses the optimistic-concurrency
race and skips instead of sending.

The lease expires, so a process that dies mid-send leaves a row another run can
pick up — at-least-once delivery, which is the honest guarantee without an
idempotent provider. The claim is diagnostics as well as protection: an operator
looking at a stuck row can see which process held it.

Revision ID: 0037_communication_dispatch_claim
Revises: 0036_communication_attempt_time
Create Date: 2026-10-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_communication_dispatch_claim"
down_revision: str | None = "0036_communication_attempt_time"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_communications",
        sa.Column("claimed_by", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "candidate_communications",
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_communications", "claimed_until")
    op.drop_column("candidate_communications", "claimed_by")
