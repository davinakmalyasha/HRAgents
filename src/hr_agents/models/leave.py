"""Leave domain models — types, policies, balances, and requests.

Statutory accrual rules (e.g., the 12-day annual minimum after 12 months) are
operator-configurable policy fields, not hardcoded constants: HR sets the
numbers, the engine applies them deterministically. Requests route through the
approval engine; only humans decide.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.approval import ApproverRole
from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class LeaveType(StrEnum):
    ANNUAL = "annual"  # cuti tahunan
    SICK = "sick"  # cuti sakit
    PERSONAL = "personal"  # izin
    MATERNITY = "maternity"  # cuti melahirkan
    PATERNITY = "paternity"  # cuti paternity
    BEREAVEMENT = "bereavement"  # cuti duka
    MARRIAGE = "marriage"  # cuti pernikahan
    UNPAID = "unpaid"  # cuti tanpa bayaran
    OTHER = "other"


class AccrualMethod(StrEnum):
    """How entitlement is granted."""

    NONE = "none"  # explicitly no balance tracking (e.g., some sick schemes)
    FLAT_MONTHLY = "flat_monthly"  # X days credited per worked month
    LUMP_SUM_ANNUAL = "lump_sum_annual"  # X days on hire anniversary
    PER_EVENT_CAP = "per_event_cap"  # no accrual; per-request cap (maternity, bereavement)


class RequestStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class LeaveTypePolicy(StrictModel):
    """Operator-configurable policy for one leave type."""

    leave_type: LeaveType
    name: str = Field(min_length=1, max_length=120)
    paid: bool = True
    requires_approval: bool = True
    approver_role: ApproverRole = ApproverRole.MANAGER
    requires_document: bool = False  # e.g., doctor's note for sick leave

    accrual_method: AccrualMethod = AccrualMethod.NONE
    days_per_year: float | None = Field(
        default=None,
        ge=0.0,
        le=365.0,
        description="Annual entitlement for lump-sum or flat accrual methods. "
        "Default for annual leave in Indonesia is 12 working days after 12 months "
        "(operator confirms).",
    )
    days_per_month: float | None = Field(default=None, ge=0.0, le=31.0)
    max_days_per_request: float | None = Field(default=None, ge=0.0, le=365.0)
    max_consecutive_days: float | None = Field(default=None, ge=0.0, le=365.0)
    min_service_months: int = Field(default=0, ge=0, le=120)
    carryover_allowed: bool = False
    carryover_max_days: float | None = Field(default=None, ge=0.0, le=365.0)
    carryover_expiry_months: int | None = Field(default=None, ge=0, le=60)
    working_days_only: bool = True

    @model_validator(mode="after")
    def _validate(self) -> LeaveTypePolicy:
        if self.accrual_method is AccrualMethod.FLAT_MONTHLY and self.days_per_month is None:
            raise ValueError(f"{self.leave_type.value}: FLAT_MONTHLY requires days_per_month")
        if self.accrual_method is AccrualMethod.LUMP_SUM_ANNUAL and self.days_per_year is None:
            raise ValueError(f"{self.leave_type.value}: LUMP_SUM_ANNUAL requires days_per_year")
        if self.accrual_method is AccrualMethod.PER_EVENT_CAP and self.max_days_per_request is None:
            raise ValueError(
                f"{self.leave_type.value}: PER_EVENT_CAP requires max_days_per_request"
            )
        if self.carryover_allowed and self.carryover_max_days is None:
            raise ValueError("carryover_allowed requires carryover_max_days")
        return self


class LeaveBalance(StrictModel):
    """Computed balance for one employee and leave type."""

    employee_id: UUID
    leave_type: LeaveType
    year: int = Field(ge=2000, le=2100)

    entitled: float = Field(default=0.0, ge=0.0)
    accrued: float = Field(default=0.0, ge=0.0)
    used: float = Field(default=0.0, ge=0.0)
    pending: float = Field(default=0.0, ge=0.0)
    carried_over: float = Field(default=0.0, ge=0.0)
    adjustment: float = Field(default=0.0)

    @property
    def available(self) -> float:
        """What the employee can still request."""
        return round(
            max(
                self.entitled + self.carried_over + self.adjustment - self.used - self.pending, 0.0
            ),
            4,
        )

    @property
    def remaining(self) -> float:
        """Physical balance (booked, excluding pending)."""
        return round(max(self.entitled + self.carried_over + self.adjustment - self.used, 0.0), 4)


class LeaveRequest(StrictModel):
    """One leave request. Routes to an approval; only humans decide."""

    id: UUID = Field(default_factory=uuid4)
    employee_id: UUID
    leave_type: LeaveType

    start_date: date
    end_date: date
    days: float = Field(gt=0.0, le=365.0)
    reason: str | None = Field(default=None, max_length=1000)
    document_id: UUID | None = None

    status: RequestStatus = RequestStatus.DRAFT
    approval_id: UUID | None = None

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_dates(self) -> LeaveRequest:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")
        return self

    @property
    def calendar_days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    def overlaps(self, other_start: date, other_end: date, *, buffer_days: int = 0) -> bool:
        """True when this request overlaps the given range (± buffer for back-to-back)."""
        padded_start = self.start_date - timedelta(days=buffer_days)
        padded_end = self.end_date + timedelta(days=buffer_days)
        return padded_start <= other_end and other_start <= padded_end
