"""Store rubric versions behind a verified gate.

The eight templates ship with the code; this table is where an operator's
version lives. ``revision`` numbers versions within a family, ``digest`` is the
content address an evaluation snapshot cites, and ``active`` marks the one the
scoring path resolves. ``version`` is the optimistic-concurrency token every
tenant table carries, not the rubric's number -- the two are different
questions and are named differently on purpose.

A version is only activatable after ``verified_by`` names a human and
``verified_note`` says why the content is trusted; the service enforces that,
and the columns exist so a manual database edit is visible as one.

Revision ID: 0027_rubric_versions
Revises: 0026_evaluation_application_fk
Create Date: 2026-10-19

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql

revision: str = "0027_rubric_versions"
down_revision: str | None = "0026_evaluation_application_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "rubric_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("family", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("template", JSONB, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified_by", sa.String(length=200), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "family", "revision", name="uq_rubric_versions_family_revision"
        ),
        sa.UniqueConstraint(
            "tenant_id", "family", "digest", name="uq_rubric_versions_family_digest"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_rubric_versions_revision"),
        sa.CheckConstraint("length(digest) = 64", name="ck_rubric_versions_digest_length"),
    )
    op.create_index("ix_rubric_versions_tenant", "rubric_versions", ["tenant_id"])
    for statement in enable_tenant_rls_sql("rubric_versions"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("rubric_versions"):
        op.execute(statement)
    op.drop_index("ix_rubric_versions_tenant", table_name="rubric_versions")
    op.drop_table("rubric_versions")
