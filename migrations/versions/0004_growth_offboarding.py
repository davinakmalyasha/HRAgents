"""Growth (reviews, goals) and offboarding pack.

Revision ID: 0004_growth_offboarding
Revises: 0003_compliance
Create Date: 2026-09-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_growth_offboarding"
down_revision: str | None = "0003_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_cycles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rating_scale_min", sa.Float(), nullable=False, server_default="1"),
        sa.Column("rating_scale_max", sa.Float(), nullable=False, server_default="5"),
        sa.Column("submission_due_on", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_review_cycles_status", "review_cycles", ["status"])

    op.create_table(
        "review_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=200), nullable=False),
        sa.Column("reviewer_role", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("ratings", sa.JSON(), nullable=False),
        sa.Column("comments", sa.Text(), nullable=False, server_default=""),
        sa.Column("submitted_by", sa.String(length=200), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped_by", sa.String(length=200), nullable=True),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_review_assignments_cycle", "review_assignments", ["cycle_id"])
    op.create_index("ix_review_assignments_employee", "review_assignments", ["employee_id"])
    op.create_index(
        "ix_review_assignments_reviewer", "review_assignments", ["reviewer_id", "status"]
    )

    op.create_table(
        "review_summaries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cycle_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("agent_draft", sa.Text(), nullable=False, server_default=""),
        sa.Column("draft_by", sa.String(length=200), nullable=True),
        sa.Column("draft_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("finalized_by", sa.String(length=200), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_review_summaries_cycle", "review_summaries", ["cycle_id"])
    op.create_index("ix_review_summaries_employee", "review_summaries", ["employee_id"])

    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("metric", sa.Text(), nullable=True),
        sa.Column("cycle_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("start_on", sa.Date(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("updates", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_goals_employee_status", "goals", ["employee_id", "status"])
    op.create_index("ix_goals_due", "goals", ["due_on"])

    op.create_table(
        "offboarding_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("applies_to_reasons", sa.JSON(), nullable=False),
        sa.Column("applies_to_roles", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "offboarding_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("last_working_day", sa.Date(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("template_name", sa.Text(), nullable=False),
        sa.Column("template_version_hash", sa.String(length=64), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("handover_notes", sa.JSON(), nullable=False),
        sa.Column("final_pay_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_offboarding_plans_employee", "offboarding_plans", ["employee_id"])
    op.create_index("ix_offboarding_plans_lwd", "offboarding_plans", ["last_working_day"])

    op.create_table(
        "offboarding_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("asset_code", sa.String(length=80), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("assigned_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("returned_on", sa.Date(), nullable=True),
        sa.Column("returned_by", sa.String(length=200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_offboarding_assets_employee", "offboarding_assets", ["employee_id"])
    op.create_index("ix_offboarding_assets_status", "offboarding_assets", ["status"])


def downgrade() -> None:
    op.drop_table("offboarding_assets")
    op.drop_table("offboarding_plans")
    op.drop_table("offboarding_templates")
    op.drop_table("goals")
    op.drop_table("review_summaries")
    op.drop_table("review_assignments")
    op.drop_table("review_cycles")
