"""Candidate domain models — the structured output of résumé deconstruction."""

from __future__ import annotations

from datetime import date, time
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import EmailStr, Field, HttpUrl, model_validator

from hr_agents.models.common import (
    ConsentRecord,
    EvidenceRef,
    ExtractionMeta,
    StrictModel,
    UtcDateTime,
    VerificationStatus,
    utc_now,
)

NonEmptyStr = Annotated[str, Field(min_length=1)]


class SkillCategory(StrEnum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    DATABASE = "database"
    CLOUD = "cloud"
    DEVOPS = "devops"
    ML_AI = "ml_ai"
    SYSTEMS = "systems"
    DATA = "data"
    OTHER = "other"


class RemotePreference(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    FLEXIBLE = "flexible"


class Channel(StrEnum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    LINKEDIN = "linkedin"


class Links(StrictModel):
    github_url: HttpUrl | None = None
    linkedin_url: HttpUrl | None = None
    website_url: HttpUrl | None = None
    orcid: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
    google_scholar_url: HttpUrl | None = None
    portfolio_url: HttpUrl | None = None


class Location(StrictModel):
    city: str | None = None
    region: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, description="IANA timezone, e.g. Asia/Jakarta")
    willing_to_relocate: bool | None = None
    remote_preference: RemotePreference | None = None


class LanguageSkill(StrictModel):
    language: NonEmptyStr
    proficiency: int | None = Field(default=None, ge=0, le=5)


class ExperienceEntry(StrictModel):
    company: NonEmptyStr
    title: NonEmptyStr
    start_date: date
    end_date: date | None = None
    duration_months: int | None = Field(default=None, ge=0)
    location: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @property
    def is_current(self) -> bool:
        return self.end_date is None


class EducationEntry(StrictModel):
    institution: NonEmptyStr
    degree: str | None = None
    field_of_study: str | None = None
    start_year: int | None = Field(default=None, ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class Skill(StrictModel):
    name: NonEmptyStr
    category: SkillCategory = SkillCategory.OTHER
    claimed_proficiency: int | None = Field(default=None, ge=0, le=5)
    last_used_year: int | None = Field(default=None, ge=1950, le=2100)
    duration_months: int | None = Field(default=None, ge=0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CertificationClaim(StrictModel):
    name: NonEmptyStr
    issuer: str | None = None
    credential_id: str | None = None
    issued_on: date | None = None
    expires_on: date | None = None
    verify_url: HttpUrl | None = None
    status: VerificationStatus = VerificationStatus.CLAIMED
    evidence: list[EvidenceRef] = Field(default_factory=list)


class Publication(StrictModel):
    title: NonEmptyStr
    venue: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)
    doi: str | None = None
    url: HttpUrl | None = None
    peer_reviewed: bool | None = None
    citation_count: int | None = Field(default=None, ge=0)
    status: VerificationStatus = VerificationStatus.CLAIMED
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ProjectEntry(StrictModel):
    name: NonEmptyStr
    description: str | None = None
    url: HttpUrl | None = None
    repo_url: HttpUrl | None = None
    tech_stack: list[str] = Field(default_factory=list)
    is_open_source: bool | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class WeeklyWindow(StrictModel):
    """A recurring availability window in the candidate's local time."""

    weekday: int = Field(ge=0, le=6, description="0 = Monday, 6 = Sunday")
    start_local: time
    end_local: time

    @model_validator(mode="after")
    def _check_window(self) -> WeeklyWindow:
        if self.end_local <= self.start_local:
            raise ValueError("end_local must be after start_local")
        return self


class AvailabilityMatrix(StrictModel):
    timezone: str = Field(default="Asia/Jakarta", description="IANA timezone")
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    weekly_windows: list[WeeklyWindow] = Field(default_factory=list)
    preferred_channels: list[Channel] = Field(default_factory=list)
    response_deadline_hours: int | None = Field(default=None, ge=1, le=336)


class CandidateProfile(StrictModel):
    """Structured, provenance-tagged representation of a candidate.

    Produced by the Résumé Deconstruction Agent. Consumed (never generated) by
    the deterministic scorer.
    """

    id: UUID = Field(default_factory=uuid4)
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    full_name: NonEmptyStr
    headline: str | None = None
    summary: str | None = Field(default=None, max_length=4000)

    emails: list[EmailStr] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    links: Links = Field(default_factory=Links)
    location: Location = Field(default_factory=Location)
    languages: list[LanguageSkill] = Field(default_factory=list)

    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    certifications: list[CertificationClaim] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)

    availability: AvailabilityMatrix | None = None
    consent: ConsentRecord = Field(default_factory=lambda: ConsentRecord(granted=False))
    extraction: ExtractionMeta | None = None
    field_confidence: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _confidence_bounds(self) -> CandidateProfile:
        for path, value in self.field_confidence.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"field_confidence[{path!r}] must be within [0, 1]")
        return self
