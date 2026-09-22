"""Offer domain models — full offer records with terms, revisions, and acceptance.

Terms are human-entered (the system never invents an offer), revisions are
append-only so negotiation history survives, and acceptance/decline is a
recorded human event — never automated.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.common import StrictModel, UtcDateTime, utc_now
from hr_agents.models.contract import ContractType


class OfferStatus(StrEnum):
    """Lifecycle of an offer record."""

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    QUEUED = "queued"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


TERMINAL_OFFER_STATUSES = frozenset(
    {
        OfferStatus.ACCEPTED,
        OfferStatus.DECLINED,
        OfferStatus.EXPIRED,
        OfferStatus.WITHDRAWN,
    }
)

# Statuses a time-driven sweep may move to EXPIRED.
EXPIRABLE_OFFER_STATUSES = frozenset(
    {OfferStatus.PENDING_APPROVAL, OfferStatus.APPROVED, OfferStatus.QUEUED}
)


class OfferTerms(StrictModel):
    """The offer on the table: position, dates, compensation, validity."""

    position_title: str = Field(min_length=1, max_length=200)
    employment_type: ContractType = ContractType.PKWTT
    start_date: date
    end_date: date | None = None
    probation_months: int | None = Field(default=None, ge=0, le=12)
    salary_amount: float = Field(ge=0.0)
    salary_currency: str = Field(default="IDR", min_length=3, max_length=8)
    notes: str = Field(default="", max_length=2000)
    expires_at: UtcDateTime | None = None

    @model_validator(mode="after")
    def _validate(self) -> OfferTerms:
        if self.end_date is not None and self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.employment_type is ContractType.PKWT and self.end_date is None:
            raise ValueError("fixed-term (PKWT) offers require an end_date")
        return self


class OfferRevision(StrictModel):
    """One append-only terms snapshot (the negotiation history)."""

    id: UUID = Field(default_factory=uuid4)
    offer_id: UUID
    revision_index: int = Field(ge=1)
    terms: OfferTerms
    changed_by: str = Field(min_length=1, max_length=200)
    changed_at: UtcDateTime = Field(default_factory=utc_now)
    note: str = Field(default="", max_length=500)


class Offer(StrictModel):
    """A full offer record: terms, status trail, and acceptance outcome."""

    id: UUID = Field(default_factory=uuid4)
    application_id: UUID
    candidate_id: UUID
    job_id: UUID | None = None

    status: OfferStatus = OfferStatus.DRAFT
    terms: OfferTerms
    revisions: list[OfferRevision] = Field(default_factory=list)

    created_by: str = Field(min_length=1, max_length=200)
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    decided_by: str | None = Field(default=None, max_length=200)
    decided_at: UtcDateTime | None = None
    queued_at: UtcDateTime | None = None
    accepted_at: UtcDateTime | None = None
    declined_at: UtcDateTime | None = None
    decline_reason: str | None = Field(default=None, max_length=500)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_OFFER_STATUSES
