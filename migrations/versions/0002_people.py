"""Employee core, contracts, approvals, tasks, and rate tables.

Revision ID: 0002_people
Revises: 0001_initial
Create Date: 2026-09-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_people"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_units",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("org_units.id", ondelete="SET NULL")),
        sa.Column("cost_center", sa.String(length=60), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("employee_number", sa.String(length=40), unique=True, nullable=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("org_unit_id", sa.Uuid(), sa.ForeignKey("org_units.id", ondelete="SET NULL")),
        sa.Column("manager_id", sa.Uuid(), sa.ForeignKey("employees.id", ondelete="SET NULL")),
        sa.Column("work_location", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("hire_date", sa.Date(), nullable=True),
        sa.Column("probation_end_date", sa.Date(), nullable=True),
        sa.Column("offboarded_on", sa.Date(), nullable=True),
        sa.Column("emergency_contact", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_employees_status", "employees", ["status"])
    op.create_index("ix_employees_org_unit", "employees", ["org_unit_id"])
    op.create_index("ix_employees_manager", "employees", ["manager_id"])

    op.create_table(
        "employee_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_employee_documents_employee", "employee_documents", ["employee_id"])
    op.create_index("ix_employee_documents_expiry", "employee_documents", ["expires_on"])

    op.create_table(
        "contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contract_type", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("probation_end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("signed_on", sa.Date(), nullable=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("employee_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("compensation_due", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_contracts_employee", "contracts", ["employee_id"])
    op.create_index("ix_contracts_end_date", "contracts", ["end_date"])
    op.create_index("ix_contracts_status", "contracts", ["status"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subject", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("requested_by_agent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assignee_role", sa.String(length=40), nullable=False),
        sa.Column("urgency", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_escalations", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_approvals_role_status", "approvals", ["assignee_role", "status"])
    op.create_index("ix_approvals_subject", "approvals", ["subject", "subject_id"])
    op.create_index("ix_approvals_sla", "approvals", ["sla_deadline"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("assignee_role", sa.String(length=40), nullable=True),
        sa.Column("assignee_id", sa.String(length=200), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("related_subject", sa.String(length=60), nullable=True),
        sa.Column("related_id", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("completed_by", sa.String(length=200), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_tasks_status_due", "tasks", ["status", "due_on"])
    op.create_index("ix_tasks_assignee", "tasks", ["assignee_role", "status"])
    op.create_index("ix_tasks_related", "tasks", ["related_subject", "related_id"])

    op.create_table(
        "rate_tables",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=2), nullable=False, server_default="ID"),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified_by", sa.String(length=200), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_rate_tables_kind", "rate_tables", ["kind", "jurisdiction"])


def downgrade() -> None:
    op.drop_table("rate_tables")
    op.drop_table("tasks")
    op.drop_table("approvals")
    op.drop_table("contracts")
    op.drop_table("employee_documents")
    op.drop_table("employees")
    op.drop_table("org_units")
