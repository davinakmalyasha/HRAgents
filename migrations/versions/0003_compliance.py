"""Compliance pack: consent registry, retention, erasure, breach workflow.

Revision ID: 0003_compliance
Revises: 0002_people
Create Date: 2026-09-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_compliance"
down_revision: str | None = "0002_people"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consent_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.String(length=120), nullable=False),
        sa.Column("lawful_basis", sa.String(length=40), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.String(length=40), nullable=False, server_default="1.0"),
        sa.Column("capture_method", sa.String(length=60), nullable=False, server_default="manual"),
        sa.Column("captured_by", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_consent_subject", "consent_records", ["subject_kind", "subject_id"])
    op.create_index("ix_consent_purpose", "consent_records", ["purpose"])

    op.create_table(
        "retention_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity", sa.String(length=40), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("retention_months", sa.Integer(), nullable=False),
        sa.Column("expiry_action", sa.String(length=16), nullable=False),
        sa.Column("jurisdiction", sa.String(length=2), nullable=False, server_default="ID"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "retention_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entity", sa.String(length=40), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_months_override", sa.Integer(), nullable=True),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("legal_hold_reason", sa.Text(), nullable=True),
        sa.Column("held_by", sa.String(length=200), nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_action", sa.String(length=16), nullable=True),
        sa.Column("purge_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_retention_entity_anchor", "retention_records", ["entity", "anchor_at"])
    op.create_index("ix_retention_subject", "retention_records", ["subject_kind", "subject_id"])
    op.create_index("ix_retention_legal_hold", "retention_records", ["legal_hold"])

    op.create_table(
        "erasure_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=60), nullable=False, server_default="manual"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("identity_verified_by", sa.String(length=200), nullable=True),
        sa.Column("identity_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("identity_method", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_by", sa.String(length=200), nullable=True),
        sa.Column("dispositions", sa.JSON(), nullable=False),
        sa.Column("consents_revoked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_erasure_status", "erasure_requests", ["status"])
    op.create_index("ix_erasure_subject", "erasure_requests", ["subject_kind", "subject_id"])
    op.create_index("ix_erasure_approval", "erasure_requests", ["approval_id"])

    op.create_table(
        "breach_incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("impact", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discovered_by", sa.String(length=200), nullable=False),
        sa.Column("template_name", sa.String(length=160), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("notifications", sa.JSON(), nullable=False),
        sa.Column("contained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(length=200), nullable=True),
        sa.Column("closure_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_breach_status", "breach_incidents", ["status"])


def downgrade() -> None:
    op.drop_table("breach_incidents")
    op.drop_table("erasure_requests")
    op.drop_table("retention_records")
    op.drop_table("retention_policies")
    op.drop_table("consent_records")
