"""WhatsApp recipient on queued communications.

Adds ``recipient_phone`` so the manual-links transport (and later the Meta Cloud
API) knows which chat a queued message belongs to. Email dispatch keeps using
``recipient``.

Revision ID: 0011_whatsapp_recipient
Revises: 0010_messaging_transport
Create Date: 2026-09-23

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_whatsapp_recipient"
down_revision: str | None = "0010_messaging_transport"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("candidate_communications", sa.Column("recipient_phone", sa.String(length=32)))


def downgrade() -> None:
    op.drop_column("candidate_communications", "recipient_phone")
