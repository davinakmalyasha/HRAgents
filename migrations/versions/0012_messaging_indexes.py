"""Indexes for the growing messaging tables.

The outbox and reply tables are append-only and never shrink, so the read paths
the scheduler, dispatcher, and inbox poll use every run must be index-backed:

- ``ix_candidate_communications_status_created`` serves the queued sweep
  (``list_queued``) and the reply-SLA pass (``list_sent``).
- ``ix_candidate_communications_message_id`` serves reply correlation, which
  compares canonicalized message ids (case-insensitive, brackets stripped) so a
  reply that echoes ``<id@host>`` still finds the row.

Revision ID: 0012_messaging_indexes
Revises: 0011_whatsapp_recipient
Create Date: 2026-09-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_messaging_indexes"
down_revision: str | None = "0011_whatsapp_recipient"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_communications",
        sa.Column("provider_message_id_normalized", sa.String(length=500)),
    )
    op.create_index(
        "ix_candidate_communications_status_created",
        "candidate_communications",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_candidate_communications_message_id",
        "candidate_communications",
        ["provider_message_id_normalized"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_communications_message_id",
        table_name="candidate_communications",
    )
    op.drop_index(
        "ix_candidate_communications_status_created",
        table_name="candidate_communications",
    )
    op.drop_column("candidate_communications", "provider_message_id_normalized")
