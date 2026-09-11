"""Payroll domain models — prepare & verify ONLY.

Hard rules encoded here:

- **No payment execution.** The product prepares a review packet; humans run
  payroll in their own systems/banks.
- **No hardcoded statutory numbers.** All rates come from verified
  :class:`~hr_agents.models.compensation.RateTable` instances; unverified tables
  block computation.
- **Human sign-off before export.** A run reaches ``APPROVED`` only via the
  approval engine with a named human decider.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class PayrollRunStatus(StrEnum):
    DRAFT = "draft"
    ASSEMBLING = "assembling"
    READY_FOR_REVIEW = "ready_for_review"
    PENDING_SIGNOFF = "pending_signoff"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPORTED = "exported"
    CANCELLED = "cancelled"


class PayrollRunKind(StrEnum):
    MONTHLY = "monthly"
    THR = "thr"  # religious holiday bonus run
    ADJUSTMENT = "adjustment"
    FINAL = "final"  # final settlement on offboarding


class AnomalySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"  # blocks sign-off


class PayrollInput(StrictModel):
    """Per-employee inputs assembled for one payroll run."""

    employee_id: UUID
    base_salary: float = Field(ge=0.0)
    fixed_allowances: float = Field(default=0.0, ge=0.0)
    variable_allowances: float = Field(default=0.0, ge=0.0)
    overtime_hours: float = Field(default=0.0, ge=0.0, le=400.0)
    absence_days: float = Field(default=0.0, ge=0.0, le=31.0)
    other_deductions: float = Field(default=0.0, ge=0.0)
    loan_deduction: float = Field(default=0.0, ge=0.0)
    bonus: float = Field(default=0.0, ge=0.0)
    note: str | None = Field(default=None, max_length=500)


class PayrollAnomaly(StrictModel):
    """A flag for human review — never auto-resolved."""

    code: str = Field(min_length=1, max_length=60)
    severity: AnomalySeverity
    employee_id: UUID | None = None
    detail: str = Field(min_length=1, max_length=500)


class PayrollLine(StrictModel):
    """Computed payroll line for one employee (review packet row)."""

    employee_id: UUID
    employee_name: str = Field(default="", max_length=200)

    # earnings
    base_salary: float = Field(ge=0.0)
    allowances: float = Field(default=0.0, ge=0.0)
    overtime_pay: float = Field(default=0.0, ge=0.0)
    bonus: float = Field(default=0.0, ge=0.0)
    gross: float = Field(ge=0.0)

    # employee deductions
    bpjs_kesehatan_employee: float = Field(default=0.0, ge=0.0)
    bpjs_jht_employee: float = Field(default=0.0, ge=0.0)
    bpjs_jp_employee: float = Field(default=0.0, ge=0.0)
    pph21: float = Field(default=0.0, ge=0.0)
    other_deductions: float = Field(default=0.0, ge=0.0)
    total_deductions: float = Field(ge=0.0)
    net: float

    # employer costs (not deducted; company expense)
    bpjs_kesehatan_employer: float = Field(default=0.0, ge=0.0)
    bpjs_jht_employer: float = Field(default=0.0, ge=0.0)
    bpjs_jp_employer: float = Field(default=0.0, ge=0.0)
    bpjs_jkk_employer: float = Field(default=0.0, ge=0.0)
    bpjs_jkm_employer: float = Field(default=0.0, ge=0.0)
    employer_cost: float = Field(default=0.0, ge=0.0)

    notes: list[str] = Field(default_factory=list)


class PayrollTotals(StrictModel):
    employees: int = Field(default=0, ge=0)
    gross: float = Field(default=0.0, ge=0.0)
    total_deductions: float = Field(default=0.0, ge=0.0)
    net: float = 0.0
    employer_cost: float = Field(default=0.0, ge=0.0)


class PayrollRun(StrictModel):
    """One payroll period: inputs → computed lines → human sign-off → export."""

    id: UUID = Field(default_factory=uuid4)
    period_year: int = Field(ge=2000, le=2100)
    period_month: int = Field(ge=1, le=12)
    kind: PayrollRunKind = PayrollRunKind.MONTHLY

    status: PayrollRunStatus = PayrollRunStatus.DRAFT
    inputs: list[PayrollInput] = Field(default_factory=list)
    lines: list[PayrollLine] = Field(default_factory=list)
    anomalies: list[PayrollAnomaly] = Field(default_factory=list)
    rate_table_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Rate table kind → id used for this run (audit reconstruction).",
    )

    approval_id: UUID | None = None
    signed_off_by: str | None = Field(default=None, max_length=200)
    signed_off_at: UtcDateTime | None = None
    exported_at: UtcDateTime | None = None

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def totals(self) -> PayrollTotals:
        return PayrollTotals(
            employees=len(self.lines),
            gross=round(sum(line.gross for line in self.lines), 2),
            total_deductions=round(sum(line.total_deductions for line in self.lines), 2),
            net=round(sum(line.net for line in self.lines), 2),
            employer_cost=round(sum(line.employer_cost for line in self.lines), 2),
        )

    @property
    def blocking_anomalies(self) -> list[PayrollAnomaly]:
        return [item for item in self.anomalies if item.severity is AnomalySeverity.ERROR]

    def can_sign_off(self) -> tuple[bool, str | None]:
        if self.status is not PayrollRunStatus.PENDING_SIGNOFF:
            return False, f"run is {self.status.value}, not pending_signoff"
        if self.blocking_anomalies:
            return False, "run has blocking anomalies and cannot be signed off"
        return True, None

    def line_for(self, employee_id: UUID) -> PayrollLine | None:
        return next((line for line in self.lines if line.employee_id == employee_id), None)

    @model_validator(mode="after")
    def _validate_status_metadata(self) -> PayrollRun:
        if self.status is PayrollRunStatus.APPROVED and self.signed_off_by is None:
            raise ValueError("approved runs require signed_off_by")
        return self
