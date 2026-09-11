"""Approval engine models — the shared human-in-the-loop queue for every department.

One generic request type serves leave requests, payroll sign-offs, contract
approvals, rejection sign-offs, document validation, and offboarding steps.
Agents may create approvals; only humans decide them.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class ApprovalSubject(StrEnum):
    """What the approval is about (extensible per department)."""

    LEAVE_REQUEST = "leave_request"
    PAYROLL_RUN = "payroll_run"
    PAYROLL_ANOMALY = "payroll_anomaly"
    CONTRACT = "contract"
    CANDIDATE_REJECTION = "candidate_rejection"
    CANDIDATE_ANOMALY = "candidate_anomaly"
    OFFER = "offer"
    DOCUMENT_VALIDATION = "document_validation"
    ONBOARDING_STEP = "onboarding_step"
    OFFBOARDING_STEP = "offboarding_step"
    EXPENSE = "expense"
    DATA_CHANGE = "data_change"
    ERASURE_REQUEST = "erasure_request"
    OTHER = "other"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class ApproverRole(StrEnum):
    HR_ADMIN = "hr_admin"
    RECRUITER_LEAD = "recruiter_lead"
    ENGINEERING_LEAD = "engineering_lead"
    FINANCE = "finance"
    MANAGER = "manager"
    DATA_PROTECTION = "data_protection"


class Urgency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


DEFAULT_SLA_HOURS: dict[Urgency, int] = {
    Urgency.LOW: 120,
    Urgency.NORMAL: 48,
    Urgency.HIGH: 24,
    Urgency.CRITICAL: 4,
}

# Statuses that end the request's life.
TERMINAL_STATUSES = frozenset(
    {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.WITHDRAWN,
    }
)


class ApprovalRequest(StrictModel):
    """One human decision waiting in a queue."""

    id: UUID = Field(default_factory=uuid4)
    subject: ApprovalSubject
    subject_id: str = Field(min_length=1, max_length=200)

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)

    requested_by: str = Field(min_length=1, max_length=200)
    requested_by_agent: bool = False
    assignee_role: ApproverRole
    urgency: Urgency = Urgency.NORMAL

    status: ApprovalStatus = ApprovalStatus.PENDING
    sla_deadline: UtcDateTime | None = None
    escalation_count: int = Field(default=0, ge=0)
    max_escalations: int = Field(default=2, ge=0)

    decided_by: str | None = Field(default=None, max_length=200)
    decided_at: UtcDateTime | None = None
    decision_reason: str | None = Field(default=None, max_length=500)

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_decisions(self) -> ApprovalRequest:
        if self.status in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED} and (
            self.decided_by is None or self.decided_at is None
        ):
            raise ValueError("decided requests require decided_by and decided_at")
        if self.status is ApprovalStatus.PENDING and self.decided_by is not None:
            raise ValueError("pending requests cannot have a decider")
        return self

    @property
    def is_open(self) -> bool:
        return self.status not in TERMINAL_STATUSES and self.status is not ApprovalStatus.ESCALATED

    @property
    def active(self) -> bool:
        return self.status in {ApprovalStatus.PENDING, ApprovalStatus.ESCALATED}

    def default_deadline(self, *, now: UtcDateTime | None = None) -> UtcDateTime:
        base = now or utc_now()
        return base + timedelta(hours=DEFAULT_SLA_HOURS[self.urgency])

    def is_overdue(self, *, now: UtcDateTime | None = None) -> bool:
        if not self.active or self.sla_deadline is None:
            return False
        return self.sla_deadline <= (now or utc_now())
