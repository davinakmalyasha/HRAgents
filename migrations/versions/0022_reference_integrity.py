"""Give the orphaned references real foreign keys.

Thirteen columns across eleven tables could name a parent row that does not
exist: growth assignments, summaries and goals (their cycle); payroll runs,
erasure requests and leave requests (their approvals); onboarding plans (their
template); offboarding plans and assets (employee, template, final pay run);
and schedule proposals (the proposal they supersede). A restore or a direct
write could put a dangling id in any of them, and the application would then
read a state it cannot represent.

Only references the services already guarantee are added here. Two candidates
stay loose on purpose, and both are named in ``remaining-work``: the growth
rows' employee ids (no employee lookup exists at creation time, so the FK
would turn a shaped 404 into a 500) and
``scheduling_availability.interviewer_id`` (there is no interviewer table to
point at yet).

Names are explicit on both sides -- model ``ForeignKey(name=...)`` and this
migration -- because ``alembic check`` compares foreign keys by name.

Revision ID: 0022_reference_integrity
Revises: 0021_compliance_calendar
Create Date: 2026-10-17

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022_reference_integrity"
down_revision: str | None = "0021_compliance_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (constraint name, table, column, referenced table, referenced column)
_FOREIGN_KEYS: tuple[tuple[str, str, str, str, str], ...] = (
    ("fk_review_assignments_cycle", "review_assignments", "cycle_id", "review_cycles", "id"),
    ("fk_review_summaries_cycle", "review_summaries", "cycle_id", "review_cycles", "id"),
    ("fk_goals_cycle", "goals", "cycle_id", "review_cycles", "id"),
    ("fk_payroll_runs_approval", "payroll_runs", "approval_id", "approvals", "id"),
    ("fk_erasure_requests_approval", "erasure_requests", "approval_id", "approvals", "id"),
    ("fk_leave_requests_approval", "leave_requests", "approval_id", "approvals", "id"),
    (
        "fk_onboarding_plans_template",
        "onboarding_plans",
        "template_id",
        "onboarding_templates",
        "id",
    ),
    ("fk_offboarding_plans_employee", "offboarding_plans", "employee_id", "employees", "id"),
    (
        "fk_offboarding_plans_template",
        "offboarding_plans",
        "template_id",
        "offboarding_templates",
        "id",
    ),
    (
        "fk_offboarding_plans_final_pay_run",
        "offboarding_plans",
        "final_pay_run_id",
        "payroll_runs",
        "id",
    ),
    ("fk_offboarding_assets_employee", "offboarding_assets", "employee_id", "employees", "id"),
    ("fk_offboarding_assets_plan", "offboarding_assets", "plan_id", "offboarding_plans", "id"),
    (
        "fk_schedule_proposals_supersedes",
        "schedule_proposals",
        "supersedes_id",
        "schedule_proposals",
        "id",
    ),
)


def upgrade() -> None:
    for name, table, column, target, target_column in _FOREIGN_KEYS:
        op.create_foreign_key(name, table, target, [column], [target_column])


def downgrade() -> None:
    for name, table, *_ in reversed(_FOREIGN_KEYS):
        op.drop_constraint(name, table, type_="foreignkey")
