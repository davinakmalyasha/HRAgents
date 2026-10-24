"""Store operator-verified credential registries.

Extraction can only report a claim. Whether a certificate is genuine is the
issuer's fact, so an operator imports the rows they checked, records the source
and certifies the registry. The table is tenant-scoped like every other, and a
registry that is not verified is not usable -- the scoring path ignores it.

Revision ID: 0031_credential_registries
Revises: 0030_provider_settings
Create Date: 2026-10-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hr_agents.db.rls import disable_tenant_rls_sql, enable_tenant_rls_sql

revision: str = "0031_credential_registries"
down_revision: str | None = "0030_provider_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "credential_registries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("issuer", sa.String(length=200), nullable=False),
        sa.Column("entries", JSONB, nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified_by", sa.String(length=200), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "issuer", "name", name="uq_credential_registries_issuer_name"
        ),
    )
    op.create_index("ix_credential_registries_tenant", "credential_registries", ["tenant_id"])
    for statement in enable_tenant_rls_sql("credential_registries"):
        op.execute(statement)


def downgrade() -> None:
    for statement in disable_tenant_rls_sql("credential_registries"):
        op.execute(statement)
    op.drop_index("ix_credential_registries_tenant", table_name="credential_registries")
    op.drop_table("credential_registries")
