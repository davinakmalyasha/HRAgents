"""Shared primitives for all HRAgents domain models."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base model: rejects unknown fields and strips whitespace."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


TIMEZONE_ENV = "HRAGENTS_TIMEZONE"
DEFAULT_TIMEZONE = "Asia/Jakarta"

_timezone: ZoneInfo | None = None


def business_timezone() -> ZoneInfo:
    """The zone business dates are read in.

    Read lazily from ``HRAGENTS_TIMEZONE`` so every entry point gets it -- the API,
    the scheduler, the scripts -- without each one having to remember to configure
    it. An install that never sets it behaves as an Indonesian one, which is who
    the dated rules (THR, PPh 21 periods, leave years) were written for.
    """
    global _timezone
    if _timezone is None:
        _timezone = ZoneInfo(os.environ.get(TIMEZONE_ENV) or DEFAULT_TIMEZONE)
    return _timezone


def set_business_timezone(name: str | None) -> None:
    """Pin the zone. Tests use it for determinism; nothing else needs to."""
    global _timezone
    _timezone = ZoneInfo(name or os.environ.get(TIMEZONE_ENV) or DEFAULT_TIMEZONE)


def business_today(at: datetime | None = None) -> date:
    """Today, in the business zone.

    ``date.today()`` reads the *host's* calendar day, so on a UTC server every
    business date is wrong for the seven hours after Jakarta has already rolled
    over -- a leave request filed "today" lands yesterday, a probation that ends
    "today" ends tomorrow, and a due-date sweep fires a day early or late.
    ``at`` exists so the boundary can be tested without waiting for 17:00 UTC.
    """
    moment = at or utc_now()
    if moment.tzinfo is None:
        raise ValueError("business_today needs an aware datetime or nothing at all")
    return moment.astimezone(business_timezone()).date()


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (append 'Z' or an offset)")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(_ensure_utc)]
"""Timezone-aware datetime, normalized to UTC."""


class VerificationStatus(StrEnum):
    """Verification state of a claimed credential or fact."""

    CLAIMED = "claimed"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class SourceType(StrEnum):
    """Where a piece of evidence came from."""

    RESUME = "resume"
    GITHUB = "github"
    LINKEDIN = "linkedin"
    QUESTIONNAIRE = "questionnaire"
    PUBLICATION = "publication"
    CERTIFICATION_REGISTRY = "certification_registry"
    CALENDAR = "calendar"
    MANUAL = "manual"


class EvidenceRef(StrictModel):
    """A pointer to the exact evidence supporting an extracted fact or score."""

    source_type: SourceType
    locator: str = Field(
        description="Stable locator, e.g. 'resume#/experience/2', 'github:owner/repo@sha'"
    )
    excerpt: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ConsentRecord(StrictModel):
    """Candidate consent state under UU PDP No. 27/2022 and GDPR-equivalent regimes."""

    granted: bool
    granted_at: UtcDateTime | None = None
    purpose: Literal["recruitment_evaluation"] = "recruitment_evaluation"
    policy_version: str = "1.0"
    expires_at: UtcDateTime | None = None
    revoked_at: UtcDateTime | None = None

    @property
    def active(self) -> bool:
        if not self.granted or self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > utc_now()


class ExtractionMeta(StrictModel):
    """Provenance for an extraction pass (agent + model + source document)."""

    agent_name: str
    agent_version: str
    model_name: str
    prompt_hash: str
    source_document_hash: str
    extracted_at: UtcDateTime = Field(default_factory=utc_now)


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic JSON serialization used for hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def payload_digest(payload: dict[str, Any]) -> str:
    """SHA-256 hex digest of a payload's canonical JSON form."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
