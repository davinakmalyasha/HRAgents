"""Normalize the WhatsApp address so an inbound reply can find its candidate.

Meta sends a ``wa_id`` as E.164 digits. The queued message stores whatever the
human typed (``0812-…``, ``+62…``), so a raw comparison misses. The normalized
column is written at queue time from the same helper the manual link composer
uses, and the inbound lookup compares that one value.

Revision ID: 0041_whatsapp_phone_normalized
Revises: 0040_telegram_recipient
Create Date: 2026-10-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_whatsapp_phone_normalized"
down_revision: str | None = "0040_telegram_recipient"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_communications",
        sa.Column("recipient_phone_normalized", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_candidate_communications_phone",
        "candidate_communications",
        ["recipient_phone_normalized"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_communications_phone", table_name="candidate_communications")
    op.drop_column("candidate_communications", "recipient_phone_normalized")
