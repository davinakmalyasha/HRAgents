"""Record when the last dispatch attempt happened.

``CandidateCommunication`` carried ``send_attempts`` and ``last_error`` but no
timestamp for the attempt, so a failed message was retried on every scheduler
tick — a dead mailbox was hit every fifteen minutes forever, and nothing in the
record could tell an operator whether the next attempt was due. The column is
what a backoff reads; the message still stays queued, so nothing is lost.

Revision ID: 0036_communication_attempt_time
Revises: 0035_email_application_drafts
Create Date: 2026-10-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_communication_attempt_time"
down_revision: str | None = "0035_email_application_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_communications",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_communications", "last_attempt_at")
