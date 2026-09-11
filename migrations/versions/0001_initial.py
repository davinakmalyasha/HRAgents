"""Initial schema: candidates, jobs, applications, evaluations, scheduling, audit, messaging.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("primary_email", sa.Text(), nullable=True),
        sa.Column("location", JSONB, nullable=True),
        sa.Column("consent", JSONB, nullable=False),
        sa.Column("profile", JSONB, nullable=False),
        sa.Column("field_confidence", JSONB, nullable=False),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("seniority", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("dimension_weights", JSONB, nullable=True),
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_channel", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True, unique=True),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("priority_score", sa.Float(), nullable=True),
        sa.Column("priority_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_applications_job_priority", "applications", ["job_id", "priority_score"])
    op.create_index("ix_applications_candidate", "applications", ["candidate_id"])

    op.create_table(
        "evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("s_tech", sa.Float(), nullable=False),
        sa.Column("sigma", sa.Float(), nullable=False),
        sa.Column("recommendation", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("document", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_evaluations_candidate_job", "evaluations", ["candidate_id", "job_id"])
    op.create_index("ix_evaluations_recommendation", "evaluations", ["recommendation"])

    op.create_table(
        "schedule_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entry_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor", JSONB, nullable=False),
        sa.Column("action", sa.String(length=200), nullable=False),
        sa.Column("subject_type", sa.String(length=100), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
        sa.Column("entry_hash", sa.String(length=64), nullable=False, unique=True),
    )
    op.create_index("ix_audit_log_subject", "audit_log", ["subject_type", "subject_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("response_sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_conversations_candidate", "conversations", ["candidate_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_messages_candidate", "messages", ["candidate_id"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("audit_log")
    op.drop_table("schedule_proposals")
    op.drop_table("evaluations")
    op.drop_table("applications")
    op.drop_table("jobs")
    op.drop_table("candidates")
