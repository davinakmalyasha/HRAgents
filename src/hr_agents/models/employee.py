"""Employee domain models — the core of the HRIS-lite records workspace."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import EmailStr, Field, model_validator

from hr_agents.models.common import (
    StrictModel,
    UtcDateTime,
    VerificationStatus,
    utc_now,
)


class EmployeeStatus(StrEnum):
    """Lifecycle states for an employee record."""

    ONBOARDING = "onboarding"
    PROBATION = "probation"
    ACTIVE = "active"
    NOTICE_PERIOD = "notice_period"
    OFFBOARDED = "offboarded"


# Allowed lifecycle transitions (deterministic guard).
EMPLOYEE_TRANSITIONS: dict[EmployeeStatus, frozenset[EmployeeStatus]] = {
    EmployeeStatus.ONBOARDING: frozenset(
        {EmployeeStatus.PROBATION, EmployeeStatus.ACTIVE, EmployeeStatus.OFFBOARDED}
    ),
    EmployeeStatus.PROBATION: frozenset(
        {EmployeeStatus.ACTIVE, EmployeeStatus.OFFBOARDED, EmployeeStatus.NOTICE_PERIOD}
    ),
    EmployeeStatus.ACTIVE: frozenset({EmployeeStatus.NOTICE_PERIOD, EmployeeStatus.OFFBOARDED}),
    EmployeeStatus.NOTICE_PERIOD: frozenset({EmployeeStatus.OFFBOARDED}),
    EmployeeStatus.OFFBOARDED: frozenset(),
}


class DocumentKind(StrEnum):
    KTP = "ktp"
    NPWP = "npwp"
    BANK_ACCOUNT = "bank_account"
    BPJS_KESEHATAN = "bpjs_kesehatan"
    BPJS_KETENAGAKERJAAN = "bpjs_ketenagakerjaan"
    CONTRACT = "contract"
    EDUCATION_CERTIFICATE = "education_certificate"
    OTHER = "other"


class OrgUnit(StrictModel):
    """A department/team node in the organization."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = None
    cost_center: str | None = Field(default=None, max_length=60)
    created_at: UtcDateTime = Field(default_factory=utc_now)


class EmployeeDocument(StrictModel):
    """A stored employee document with expiry and verification state."""

    id: UUID = Field(default_factory=uuid4)
    employee_id: UUID
    kind: DocumentKind
    storage_key: str = Field(min_length=1, description="Object storage key")
    filename: str | None = Field(default=None, max_length=255)
    sha256: str = Field(min_length=64, max_length=64)
    issued_on: date | None = None
    expires_on: date | None = None
    status: VerificationStatus = VerificationStatus.CLAIMED
    uploaded_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def expired(self) -> bool:
        return self.expires_on is not None and self.expires_on < date.today()


class EmergencyContact(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    relationship: str | None = Field(default=None, max_length=60)
    phone: str | None = Field(default=None, max_length=32)


class Employee(StrictModel):
    """An employee record. Personal data is minimized to what HR operations need."""

    id: UUID = Field(default_factory=uuid4)
    employee_number: str | None = Field(default=None, max_length=40)

    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)

    job_title: str | None = Field(default=None, max_length=120)
    org_unit_id: UUID | None = None
    manager_id: UUID | None = None
    work_location: str | None = Field(default=None, max_length=120)

    status: EmployeeStatus = EmployeeStatus.ONBOARDING
    hire_date: date | None = None
    probation_end_date: date | None = None
    offboarded_on: date | None = None

    emergency_contact: EmergencyContact | None = None
    documents: list[EmployeeDocument] = Field(default_factory=list)

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate_dates(self) -> Employee:
        if (
            self.probation_end_date is not None
            and self.hire_date is not None
            and self.probation_end_date < self.hire_date
        ):
            raise ValueError("probation_end_date cannot precede hire_date")
        if self.status is EmployeeStatus.OFFBOARDED and self.offboarded_on is None:
            raise ValueError("offboarded employees require offboarded_on")
        return self

    def can_transition_to(self, target: EmployeeStatus) -> bool:
        return target in EMPLOYEE_TRANSITIONS[self.status]
