"""Index tenant_id on every table that lacked it.

Row-level security adds ``tenant_id = ...`` to every query, so an unindexed tenant column
makes the isolation layer a sequential scan of the whole table on every read. The security
mechanism was the performance floor for the whole schema: no table in this database had an
index on the column its own security policy filters by.

Rather than hand-editing 35 ``__table_args__`` blocks -- 35 chances to forget, which is how
fourteen migrations went by with none -- the index is now attached by
``db.base.ensure_tenant_indexes()`` as the mappers configure, and this migration brings the
existing tables into line with what the models now declare. A table added from here on
gets the index automatically and cannot be missed.

What this closes is not "add some indexes" but "the predicate every tenant-scoped read
performs had no index".

Revision ID: 0018_tenant_indexes
Revises: 0017_onboarding_stores
Create Date: 2026-10-05

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_tenant_indexes"
down_revision: str | None = "0017_onboarding_stores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The tables that gained a tenant index here, held as a tuple so the downgrade cannot
# drift from the upgrade. Mirrors what ensure_tenant_indexes() computes from the models.
_INDEXED = (
    "applications",
    "approvals",
    "audit_log",
    "breach_incidents",
    "candidate_communications",
    "candidate_documents",
    "candidate_replies",
    "candidates",
    "consent_records",
    "contracts",
    "conversations",
    "employee_documents",
    "employees",
    "erasure_requests",
    "evaluation_overrides",
    "evaluations",
    "feedback_reports",
    "goals",
    "jobs",
    "messages",
    "offboarding_assets",
    "offboarding_plans",
    "offboarding_templates",
    "offer_revisions",
    "offers",
    "org_units",
    "rate_tables",
    "retention_policies",
    "retention_records",
    "review_assignments",
    "review_cycles",
    "review_summaries",
    "schedule_proposals",
    "scheduling_availability",
    "tasks",
)


def upgrade() -> None:
    for table in _INDEXED:
        op.create_index(f"ix_{table}_tenant", table, ["tenant_id"])


def downgrade() -> None:
    for table in reversed(_INDEXED):
        op.drop_index(f"ix_{table}_tenant", table_name=table)
