"""Contract domain models — PKWT/PKWTT lifecycle and expiry math inputs."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class ContractType(StrEnum):
    """Indonesian employment contract types."""

    PKWTT = "pkwtt"  # permanent (kontrak tetap)
    PKWT = "pkwt"  # fixed term
    INTERNSHIP = "internship"
    FREELANCE = "freelance"


class ContractStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRING = "expiring"  # within the warning window
    EXPIRED = "expired"
    TERMINATED = "terminated"
    COMPLETED = "completed"  # PKWT ran its course


# PKWT statutory constraints (structure only — verify periods against current
# regulation before enforcing hard blocks; the service treats these as defaults).
PKWT_MAX_MONTHS_TOTAL = 60
PKWT_MAX_EXTENSIONS = 1
PROBATION_MAX_MONTHS = 3
PROBATION_ALLOWED_TYPES = frozenset({ContractType.PKWTT})


class Contract(StrictModel):
    """One employment contract for one employee."""

    id: UUID = Field(default_factory=uuid4)
    employee_id: UUID
    contract_type: ContractType

    start_date: date
    end_date: date | None = None
    probation_end_date: date | None = None

    status: ContractStatus = ContractStatus.DRAFT
    signed_on: date | None = None
    document_id: UUID | None = None

    # PKWT completion compensation flag (uang kompensasi) — structure only.
    compensation_due: bool = False
    notes: str | None = Field(default=None, max_length=2000)

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate(self) -> Contract:
        if self.end_date is not None and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.contract_type is ContractType.PKWT and self.end_date is None:
            raise ValueError("PKWT contracts require an end_date")
        if self.probation_end_date is not None:
            if self.contract_type not in PROBATION_ALLOWED_TYPES:
                raise ValueError(
                    f"probation is not permitted for {self.contract_type.value} contracts"
                )
            if self.probation_end_date <= self.start_date:
                raise ValueError("probation_end_date must be after start_date")
        return self

    @property
    def is_open_ended(self) -> bool:
        return self.end_date is None

    def months_of_service(self, *, as_of: date | None = None) -> int:
        """Completed months since the contract start."""
        end = as_of or date.today()
        anchor = min(end, self.end_date) if self.end_date is not None else end
        months = (anchor.year - self.start_date.year) * 12 + (anchor.month - self.start_date.month)
        if anchor.day < self.start_date.day:
            months -= 1
        return max(months, 0)

    def days_until_expiry(self, *, as_of: date | None = None) -> int | None:
        if self.end_date is None:
            return None
        return (self.end_date - (as_of or date.today())).days

    def expired(self, *, as_of: date | None = None) -> bool:
        days = self.days_until_expiry(as_of=as_of)
        return days is not None and days < 0
