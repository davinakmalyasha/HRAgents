"""Persistence gap fill: documents, overrides, feedback, availability.

Adds the columns and tables the API services need for durable Postgres-backed
stores: application consent/scoring/timeline fields, evaluation context,
scheduling proposal flags, plus candidate documents, override log, feedback
reports, and interviewer availability.

Revision ID: 0005_persistence
Revises: 0004_growth_offboarding
Create Date: 2026-09-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_persistence"
down_revision: str | None = "0004_growth_offboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("applications", sa.Column("payload_hash", sa.String(length=64), nullable=True))
    op.add_column("applications", sa.Column("consent", JSONB, nullable=True))
    op.add_column("applications", sa.Column("s_tech", sa.Float(), nullable=True))
    op.add_column("applications", sa.Column("sigma", sa.Float(), nullable=True))
    op.add_column("applications", sa.Column("recommendation", sa.String(length=32), nullable=True))
    op.add_column("applications", sa.Column("timeline", JSONB, nullable=True))

    op.add_column("evaluations", sa.Column("application_id", sa.Uuid(), nullable=True))
    op.add_column("evaluations", sa.Column("candidate_name", sa.Text(), nullable=True))
    op.add_column("evaluations", sa.Column("job_title", sa.Text(), nullable=True))
    op.add_column("evaluations", sa.Column("source", sa.String(length=32), nullable=True))
    op.add_column("evaluations", sa.Column("policy", JSONB, nullable=True))
    op.create_index("ix_evaluations_application_id", "evaluations", ["application_id"])

    op.add_column(
        "schedule_proposals",
        sa.Column("requires_human_approval", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "schedule_proposals",
        sa.Column("needs_human_reconciliation", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "schedule_proposals", sa.Column("created_by", sa.String(length=200), nullable=True)
    )

    op.create_table(
        "candidate_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=200), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_candidate_documents_sha256", "candidate_documents", ["sha256"])

    op.create_table(
        "evaluation_overrides",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "evaluation_id",
            sa.Uuid(),
            sa.ForeignKey("evaluations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer_id", sa.String(length=200), nullable=False),
        sa.Column("reviewer_role", sa.String(length=40), nullable=False),
        sa.Column("override_decision", sa.String(length=40), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_evaluation_overrides_evaluation", "evaluation_overrides", ["evaluation_id"])

    op.create_table(
        "feedback_reports",
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("report", JSONB, nullable=False),
        sa.Column("saved_by", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "scheduling_availability",
        sa.Column("interviewer_id", sa.Uuid(), primary_key=True),
        sa.Column("slots", JSONB, nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("scheduling_availability")
    op.drop_table("feedback_reports")
    op.drop_index("ix_evaluation_overrides_evaluation", table_name="evaluation_overrides")
    op.drop_table("evaluation_overrides")
    op.drop_index("ix_candidate_documents_sha256", table_name="candidate_documents")
    op.drop_table("candidate_documents")

    op.drop_column("schedule_proposals", "created_by")
    op.drop_column("schedule_proposals", "needs_human_reconciliation")
    op.drop_column("schedule_proposals", "requires_human_approval")

    op.drop_index("ix_evaluations_application_id", table_name="evaluations")
    op.drop_column("evaluations", "policy")
    op.drop_column("evaluations", "source")
    op.drop_column("evaluations", "job_title")
    op.drop_column("evaluations", "candidate_name")
    op.drop_column("evaluations", "application_id")

    op.drop_column("applications", "timeline")
    op.drop_column("applications", "recommendation")
    op.drop_column("applications", "sigma")
    op.drop_column("applications", "s_tech")
    op.drop_column("applications", "consent")
    op.drop_column("applications", "payload_hash")
