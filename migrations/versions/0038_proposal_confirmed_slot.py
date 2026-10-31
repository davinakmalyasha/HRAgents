"""Record which proposed slot the interview was actually confirmed for.

A proposal carries the slots it offered, so a confirmation could not say which
time was agreed. The automatic exclusion added in the previous commit therefore
treated every slot of a confirmed proposal as held until it passed — safe, but it
under-offered an interviewer for days. This column records the agreed slot when
the human names one (or when there was only one to name), so only that time is
held.

Revision ID: 0038_proposal_confirmed_slot
Revises: 0037_communication_dispatch_claim
Create Date: 2026-10-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_proposal_confirmed_slot"
down_revision: str | None = "0037_communication_dispatch_claim"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("schedule_proposals", sa.Column("confirmed_slot", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("schedule_proposals", "confirmed_slot")
