"""Leave API schemas."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field

from hr_agents.models import (
    AccrualMethod,
    ApproverRole,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    LeaveTypePolicy,
    RequestStatus,
    StrictModel,
)


class PolicySet(StrictModel):
    leave_type: LeaveType
    name: str = Field(min_length=1, max_length=120)
    by: str = Field(min_length=1, max_length=200)
    paid: bool = True
    requires_approval: bool = True
    approver_role: ApproverRole = ApproverRole.MANAGER
    requires_document: bool = False
    accrual_method: AccrualMethod = AccrualMethod.NONE
    days_per_year: float | None = Field(default=None, ge=0.0, le=365.0)
    days_per_month: float | None = Field(default=None, ge=0.0, le=31.0)
    max_days_per_request: float | None = Field(default=None, ge=0.0, le=365.0)
    max_consecutive_days: float | None = Field(default=None, ge=0.0, le=365.0)
    min_service_months: int = Field(default=0, ge=0, le=120)
    carryover_allowed: bool = False
    carryover_max_days: float | None = Field(default=None, ge=0.0, le=365.0)
    working_days_only: bool = True

    def to_policy(self) -> LeaveTypePolicy:
        return LeaveTypePolicy(**self.model_dump(exclude={"by"}))


class PolicyView(StrictModel):
    leave_type: LeaveType
    name: str
    paid: bool
    requires_approval: bool
    approver_role: ApproverRole
    requires_document: bool
    accrual_method: AccrualMethod
    days_per_year: float | None
    days_per_month: float | None
    max_days_per_request: float | None
    min_service_months: int
    carryover_allowed: bool
    carryover_max_days: float | None

    @classmethod
    def from_model(cls, policy: LeaveTypePolicy) -> PolicyView:
        return cls(
            leave_type=policy.leave_type,
            name=policy.name,
            paid=policy.paid,
            requires_approval=policy.requires_approval,
            approver_role=policy.approver_role,
            requires_document=policy.requires_document,
            accrual_method=policy.accrual_method,
            days_per_year=policy.days_per_year,
            days_per_month=policy.days_per_month,
            max_days_per_request=policy.max_days_per_request,
            min_service_months=policy.min_service_months,
            carryover_allowed=policy.carryover_allowed,
            carryover_max_days=policy.carryover_max_days,
        )


class BalanceView(StrictModel):
    employee_id: UUID
    leave_type: LeaveType
    year: int
    entitled: float
    used: float
    pending: float
    carried_over: float
    adjustment: float
    available: float

    @classmethod
    def from_model(cls, balance: LeaveBalance) -> BalanceView:
        return cls(
            employee_id=balance.employee_id,
            leave_type=balance.leave_type,
            year=balance.year,
            entitled=balance.entitled,
            used=balance.used,
            pending=balance.pending,
            carried_over=balance.carried_over,
            adjustment=balance.adjustment,
            available=balance.available,
        )


class BalanceAdjust(StrictModel):
    days: float
    by: str = Field(min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=2000, le=2100)
    reason: str | None = Field(default=None, max_length=500)


class LeaveRequestCreate(StrictModel):
    employee_id: UUID
    leave_type: LeaveType
    start_date: date
    end_date: date
    requested_by: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)
    document_id: UUID | None = None


class RequestAction(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


class LeaveRequestView(StrictModel):
    id: UUID
    employee_id: UUID
    leave_type: LeaveType
    start_date: date
    end_date: date
    days: float
    status: RequestStatus
    approval_id: UUID | None
    reason: str | None

    @classmethod
    def from_model(cls, request: LeaveRequest) -> LeaveRequestView:
        return cls(
            id=request.id,
            employee_id=request.employee_id,
            leave_type=request.leave_type,
            start_date=request.start_date,
            end_date=request.end_date,
            days=request.days,
            status=request.status,
            approval_id=request.approval_id,
            reason=request.reason,
        )


class HolidaySet(StrictModel):
    holidays: list[date]
    by: str = Field(min_length=1, max_length=200)
