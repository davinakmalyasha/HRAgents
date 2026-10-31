"""Commit a decision and the subject sync it owes in one transaction.

The reconcile job alone was a repair path: it could apply a decision whose
subject update was lost, but only *after* the two stores had disagreed. This
table is the transactional half. `ApprovalEngine.decide` writes the approved or
rejected row and this outbox row in one Postgres transaction, so there is no
window in which the decision exists and the work it implies does not. The
reconcile job then consumes the row idempotently.

``unique(approval_id)`` is what makes a retried transition safe — it cannot
queue the same decision twice. The backfill covers approvals decided in the last
seven days before the upgrade, which is the same window the repair job scanned.

Revision ID: 0039_approval_sync_outbox
Revises: 0038_proposal_confirmed_slot
Create Date: 2026-10-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql

revision: str = "0039_approval_sync_outbox"
down_revision: str | None = "0038_proposal_confirmed_slot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_pending_approval_syncs_approval"
_UNIQUE = "uq_pending_approval_syncs_approval"
_CHECK = "ck_pending_approval_syncs_attempts"


def upgrade() -> None:
    op.create_table(
        "pending_approval_syncs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=True),
    )
    op.create_foreign_key(
        _FK, "pending_approval_syncs", "approvals", ["approval_id"], ["id"], ondelete="CASCADE"
    )
    op.create_unique_constraint(_UNIQUE, "pending_approval_syncs", ["approval_id"])
    op.create_check_constraint(_CHECK, "pending_approval_syncs", "attempts >= 0")
    op.create_index("ix_pending_approval_syncs_tenant", "pending_approval_syncs", ["tenant_id"])
    op.create_index(
        "ix_pending_approval_syncs_queue",
        "pending_approval_syncs",
        ["consumed_at", "created_at"],
    )
    for statement in enable_tenant_rls_sql("pending_approval_syncs"):
        op.execute(statement)

    # Backfill: decisions made before this table existed get their outbox row,
    # limited to the window the repair job already scanned. The unique constraint
    # makes a replay of this statement a no-op.
    op.execute(
        """
        INSERT INTO pending_approval_syncs
            (id, tenant_id, version, approval_id, subject, subject_id, decision,
             created_at, attempts, last_error, consumed_at, outcome)
        SELECT gen_random_uuid(), a.tenant_id, 0, a.id, a.subject, a.subject_id,
               a.status, a.decided_at, 0, NULL, NULL, NULL
        FROM approvals a
        WHERE a.status IN ('approved', 'rejected', 'withdrawn', 'expired')
          AND a.decided_at IS NOT NULL
          AND a.decided_at >= now() - interval '7 days'
          AND NOT EXISTS (
              SELECT 1 FROM pending_approval_syncs s WHERE s.approval_id = a.id
          )
        """
    )


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("pending_approval_syncs"):
        op.execute(statement)
    op.drop_index("ix_pending_approval_syncs_queue", table_name="pending_approval_syncs")
    op.drop_index("ix_pending_approval_syncs_tenant", table_name="pending_approval_syncs")
    op.drop_constraint(_CHECK, "pending_approval_syncs", type_="check")
    op.drop_constraint(_UNIQUE, "pending_approval_syncs", type_="unique")
    op.drop_constraint(_FK, "pending_approval_syncs", type_="foreignkey")
    op.drop_table("pending_approval_syncs")
