"""Record model token usage per evaluation.

A provider bills tokens; the ledger lets the operations page and the metrics
endpoint answer what a model consumed without walking every evaluation's JSON.
The evaluation reference is nullable and SET NULL: deleting an evaluation must
not erase the fact that tokens were spent.

Revision ID: 0032_llm_usage
Revises: 0031_credential_registries
Create Date: 2026-10-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql

revision: str = "0032_llm_usage"
down_revision: str | None = "0031_credential_registries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_llm_usage_evaluation"


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evaluation_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_foreign_key(
        _FK, "llm_usage", "evaluations", ["evaluation_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_llm_usage_tenant", "llm_usage", ["tenant_id"])
    op.create_index("ix_llm_usage_created", "llm_usage", ["tenant_id", "created_at"])
    for statement in enable_tenant_rls_sql("llm_usage"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("llm_usage"):
        op.execute(statement)
    op.drop_index("ix_llm_usage_created", table_name="llm_usage")
    op.drop_index("ix_llm_usage_tenant", table_name="llm_usage")
    op.drop_constraint(_FK, "llm_usage", type_="foreignkey")
    op.drop_table("llm_usage")
