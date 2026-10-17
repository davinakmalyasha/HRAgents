"""Put the model's invariants under the database (CHECK constraints).

No CHECK constraint existed anywhere: every rule lived in Pydantic, so a
restore, a migration replay or a direct SQL write could leave a row the domain
cannot represent -- money with a wrong sign, a payslip whose totals do not add
up, a leave request ending before it starts, a cancelled payroll run with no
reason, a finalized review summary with no author.

Every constraint here mirrors an existing model validator (the field bounds on
the model, or the ``model_validator`` the services enforce); none invents a
rule. The ``PayrollLine`` arithmetic identities are the same four
``check_invariants`` asserts, which is the point: the model guards every
construction, the table guards every write, and they must agree.

Revision ID: 0023_check_constraints
Revises: 0022_reference_integrity
Create Date: 2026-10-17

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023_check_constraints"
down_revision: str | None = "0022_reference_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY_COLUMNS = (
    "base_salary",
    "allowances",
    "overtime_pay",
    "bonus",
    "gross",
    "bpjs_kesehatan_employee",
    "bpjs_jht_employee",
    "bpjs_jp_employee",
    "pph21",
    "other_deductions",
    "total_deductions",
    "bpjs_kesehatan_employer",
    "bpjs_jht_employer",
    "bpjs_jp_employer",
    "bpjs_jkk_employer",
    "bpjs_jkm_employer",
    "employer_cost",
)

# (constraint name, table, condition) -- order matters only for readability.
_CHECK_CONSTRAINTS: tuple[tuple[str, str, str], ...] = (
    (
        "ck_payroll_runs_period_year",
        "payroll_runs",
        "period_year BETWEEN 2000 AND 2100",
    ),
    ("ck_payroll_runs_period_month", "payroll_runs", "period_month BETWEEN 1 AND 12"),
    (
        "ck_payroll_runs_cancel_pairing",
        "payroll_runs",
        "(cancelled_at IS NULL AND cancel_reason IS NULL) "
        "OR (cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL)",
    ),
    (
        "ck_payroll_runs_approved_signed_off_by",
        "payroll_runs",
        "status <> 'approved' OR signed_off_by IS NOT NULL",
    ),
    *[
        (f"ck_payroll_lines_{column}_nonneg", "payroll_lines", f"{column} >= 0")
        for column in _MONEY_COLUMNS
    ],
    ("ck_payroll_lines_thr_months", "payroll_lines", "thr_months BETWEEN 0 AND 24"),
    (
        "ck_payroll_lines_gross_sum",
        "payroll_lines",
        "round(gross, 2) = round(base_salary + allowances + overtime_pay + bonus, 2)",
    ),
    (
        "ck_payroll_lines_deductions_sum",
        "payroll_lines",
        "round(total_deductions, 2) = round(bpjs_kesehatan_employee + bpjs_jht_employee "
        "+ bpjs_jp_employee + pph21 + other_deductions, 2)",
    ),
    (
        "ck_payroll_lines_net_identity",
        "payroll_lines",
        "round(net, 2) = round(gross - total_deductions, 2)",
    ),
    (
        "ck_payroll_lines_employer_cost_sum",
        "payroll_lines",
        "round(employer_cost, 2) = round(bpjs_kesehatan_employer + bpjs_jht_employer "
        "+ bpjs_jp_employer + bpjs_jkk_employer + bpjs_jkm_employer, 2)",
    ),
    ("ck_leave_requests_days", "leave_requests", "days > 0 AND days <= 365"),
    ("ck_leave_requests_date_order", "leave_requests", "end_date >= start_date"),
    ("ck_goals_progress_percent", "goals", "progress_percent BETWEEN 0 AND 100"),
    (
        "ck_review_cycles_period_order",
        "review_cycles",
        "period_end >= period_start",
    ),
    (
        "ck_review_cycles_rating_scale",
        "review_cycles",
        "rating_scale_max > rating_scale_min",
    ),
    (
        "ck_review_summaries_finalized_fields",
        "review_summaries",
        "status <> 'finalized' OR (final_text IS NOT NULL "
        "AND finalized_by IS NOT NULL AND finalized_at IS NOT NULL)",
    ),
    (
        "ck_employees_probation_after_hire",
        "employees",
        "probation_end_date IS NULL OR hire_date IS NULL OR probation_end_date >= hire_date",
    ),
    (
        "ck_employees_offboarded_date",
        "employees",
        "status <> 'offboarded' OR offboarded_on IS NOT NULL",
    ),
    (
        "ck_contracts_end_after_start",
        "contracts",
        "end_date IS NULL OR end_date > start_date",
    ),
    (
        "ck_contracts_pkwt_requires_end",
        "contracts",
        "contract_type <> 'pkwt' OR end_date IS NOT NULL",
    ),
    (
        "ck_contracts_probation_after_start",
        "contracts",
        "probation_end_date IS NULL OR probation_end_date > start_date",
    ),
    (
        "ck_contracts_probation_pkwtt_only",
        "contracts",
        "probation_end_date IS NULL OR contract_type = 'pkwtt'",
    ),
    ("ck_approvals_escalation_count", "approvals", "escalation_count >= 0"),
    ("ck_approvals_max_escalations", "approvals", "max_escalations >= 0"),
    (
        "ck_approvals_decided_fields",
        "approvals",
        "status NOT IN ('approved', 'rejected') "
        "OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
    ),
    (
        "ck_approvals_pending_no_decider",
        "approvals",
        "status <> 'pending' OR decided_by IS NULL",
    ),
    (
        "ck_retention_policies_months",
        "retention_policies",
        "retention_months BETWEEN 1 AND 600",
    ),
    (
        "ck_retention_records_override_range",
        "retention_records",
        "retention_months_override IS NULL OR retention_months_override BETWEEN 1 AND 600",
    ),
    (
        "ck_retention_records_hold_reason",
        "retention_records",
        "NOT legal_hold OR (legal_hold_reason IS NOT NULL AND legal_hold_reason <> '')",
    ),
    (
        "ck_retention_records_hold_not_purged",
        "retention_records",
        "NOT legal_hold OR purged_at IS NULL",
    ),
    (
        "ck_erasure_requests_consents_revoked",
        "erasure_requests",
        "consents_revoked >= 0",
    ),
    (
        "ck_candidate_communications_send_attempts",
        "candidate_communications",
        "send_attempts >= 0",
    ),
    ("ck_evaluations_s_tech_range", "evaluations", "s_tech BETWEEN 0 AND 1"),
    ("ck_evaluations_sigma_nonneg", "evaluations", "sigma >= 0"),
    ("ck_offer_revisions_index", "offer_revisions", "revision_index >= 1"),
)


def upgrade() -> None:
    for name, table, condition in _CHECK_CONSTRAINTS:
        op.create_check_constraint(name, table, condition)


def downgrade() -> None:
    for name, table, _condition in reversed(_CHECK_CONSTRAINTS):
        op.drop_constraint(name, table, type_="check")
