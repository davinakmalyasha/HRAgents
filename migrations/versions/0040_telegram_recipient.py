"""Address a queued Telegram message with its chat id.

`candidate_communications` addressed email and WhatsApp; Telegram had a live
sender and no way for the queue to name a recipient, so the channel could not be
dispatched at all. The column is nullable, so existing rows and the email path
are unchanged.

Revision ID: 0040_telegram_recipient
Revises: 0039_approval_sync_outbox
Create Date: 2026-10-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_telegram_recipient"
down_revision: str | None = "0039_approval_sync_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_communications",
        sa.Column("recipient_telegram_chat_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_communications", "recipient_telegram_chat_id")
