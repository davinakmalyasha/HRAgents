"""Map an interviewer to a calendar, so free/busy can feed the registry.

The free/busy adapter was live but nothing named which calendar belonged to
which interviewer. This nullable column is that directory entry: an operator (or
the scheduling API) sets it, and the calendar-sync job refreshes the slots from
the provider's free/busy answer. Rows without one keep whatever slots a human
entered.

Revision ID: 0042_interviewer_calendar
Revises: 0041_whatsapp_phone_normalized
Create Date: 2026-10-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_interviewer_calendar"
down_revision: str | None = "0041_whatsapp_phone_normalized"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scheduling_availability",
        sa.Column("calendar_id", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheduling_availability", "calendar_id")
