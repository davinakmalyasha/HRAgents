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
from hr_agents.models.money import ZERO, Money, add, sub, sum_money


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
    base_salary: Money = Field(ge=0.0)
    fixed_allowances: Money = Field(default=ZERO, ge=0.0)
    variable_allowances: Money = Field(default=ZERO, ge=0.0)
    overtime_hours: float = Field(default=0.0, ge=0.0, le=400.0)
    absence_days: float = Field(default=0.0, ge=0.0, le=31.0)
    service_months: int = Field(
        default=0,
        ge=0,
        le=1200,
        description=(
            "Completed months of service, used only by a `thr` run to pick the "
            "entitlement row from the verified `thr_formula` table. Ignored on a "
            "monthly run."
        ),
    )
    other_deductions: Money = Field(default=ZERO, ge=0.0)
    loan_deduction: Money = Field(default=ZERO, ge=0.0)
    bonus: Money = Field(default=ZERO, ge=0.0)
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
    base_salary: Money = Field(ge=0.0)
    allowances: Money = Field(default=ZERO, ge=0.0)
    overtime_pay: Money = Field(default=ZERO, ge=0.0)
    bonus: Money = Field(default=ZERO, ge=0.0)
    gross: Money = Field(ge=0.0)

    # employee deductions
    bpjs_kesehatan_employee: Money = Field(default=ZERO, ge=0.0)
    bpjs_jht_employee: Money = Field(default=ZERO, ge=0.0)
    bpjs_jp_employee: Money = Field(default=ZERO, ge=0.0)
    pph21: Money = Field(default=ZERO, ge=0.0)
    other_deductions: Money = Field(default=ZERO, ge=0.0)
    total_deductions: Money = Field(ge=0.0)
    net: Money

    # employer costs (not deducted; company expense)
    bpjs_kesehatan_employer: Money = Field(default=ZERO, ge=0.0)
    bpjs_jht_employer: Money = Field(default=ZERO, ge=0.0)
    bpjs_jp_employer: Money = Field(default=ZERO, ge=0.0)
    bpjs_jkk_employer: Money = Field(default=ZERO, ge=0.0)
    bpjs_jkm_employer: Money = Field(default=ZERO, ge=0.0)
    employer_cost: Money = Field(default=ZERO, ge=0.0)

    # Termination (THR) entitlement, in whole months of wages. Zero on a monthly
    # run. Present so a THR payslip is auditable: the figure an employee checks
    # first is "how many months did they say I had", not the rupiah total.
    thr_months: int = Field(default=0, ge=0, le=24)

    notes: list[str] = Field(default_factory=list)

    def check_invariants(self) -> None:
        """The arithmetic identities a payslip must satisfy, asserted on the way out.

        Money is exact now, so these are not approximations that "usually" hold --
        they are identities, and a violation means a bug rather than a rounding
        artefact. Having them here rather than in a test means a line assembled
        anywhere -- a service, a test, a future import path -- is checked the moment
        it exists.

        They are what an employee's bank reconciliation compares against, which is
        why they are worth asserting at construction rather than at export.
        """
        earnings = add(self.base_salary, self.allowances, self.overtime_pay, self.bonus)
        if earnings != self.gross:
            raise ValueError(
                f"gross {self.gross} does not equal base {self.base_salary} + allowances "
                f"{self.allowances} + overtime {self.overtime_pay} + bonus {self.bonus} "
                f"= {earnings}"
            )
        deductions = add(
            self.bpjs_kesehatan_employee,
            self.bpjs_jht_employee,
            self.bpjs_jp_employee,
            self.pph21,
            self.other_deductions,
        )
        if deductions != self.total_deductions:
            raise ValueError(
                f"total_deductions {self.total_deductions} does not equal the sum of "
                f"its parts {deductions}"
            )
        if sub(self.gross, self.total_deductions) != self.net:
            raise ValueError(
                f"net {self.net} does not equal gross {self.gross} - deductions "
                f"{self.total_deductions}"
            )
        employer = add(
            self.bpjs_kesehatan_employer,
            self.bpjs_jht_employer,
            self.bpjs_jp_employer,
            self.bpjs_jkk_employer,
            self.bpjs_jkm_employer,
        )
        if employer != self.employer_cost:
            raise ValueError(
                f"employer_cost {self.employer_cost} does not equal the sum of the "
                f"employer shares {employer}"
            )

    # `net` is deliberately unconstrained (`Money` with no `ge=0`). A negative net is
    # a real state the service records as a blocking `negative_net` anomaly and a
    # human corrects, so it must be representable -- which is also why this method
    # asserts arithmetic identities only and makes no judgement about the values.


class PayrollTotals(StrictModel):
    employees: int = Field(default=0, ge=0)
    gross: Money = Field(default=ZERO, ge=0.0)
    total_deductions: Money = Field(default=ZERO, ge=0.0)
    net: Money = ZERO
    employer_cost: Money = Field(default=ZERO, ge=0.0)


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
        # Exact, and quantised once at the end -- summing 200 quantised Decimals
        # is already exact, so this is belt-and-braces rather than a correction.
        return PayrollTotals(
            employees=len(self.lines),
            gross=sum_money([line.gross for line in self.lines]),
            total_deductions=sum_money([line.total_deductions for line in self.lines]),
            net=sum_money([line.net for line in self.lines]),
            employer_cost=sum_money([line.employer_cost for line in self.lines]),
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
