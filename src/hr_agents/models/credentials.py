"""Operator-verified credential registries.

Extraction can only report what a document *claims*. Whether a certificate is
genuine is a fact an issuer owns, so an operator imports the credentials they
can check, records the source, and verifies the registry. Until then the
registry is not usable and scoring behaves exactly as before; once one is
usable, a claim that does not match it stops counting as verified.

The registry is deliberately a list rather than an integration: BNSP, AWS,
Google, ACCA and friends all publish different lookup shapes, and the first
useful version is a human copying the IDs they verified.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models.common import (
    StrictModel,
    UtcDateTime,
    VerificationStatus,
    Versioned,
    utc_now,
)


class CredentialEntry(StrictModel):
    """One credential an operator has checked against its issuer."""

    name: str = Field(min_length=1, max_length=200)
    status: VerificationStatus = Field(
        default=VerificationStatus.VERIFIED,
        description=(
            "Verified, failed or expired. `claimed` and `unverified` are not "
            "answers a registry can give."
        ),
    )
    credential_id: str | None = Field(default=None, max_length=200)
    expires_on: date | None = None
    notes: str | None = Field(default=None, max_length=500)

    def effective_status(self, *, as_of: date) -> VerificationStatus:
        """An entry past its expiry is expired, whatever the row says."""
        if self.expires_on is not None and self.expires_on < as_of:
            return VerificationStatus.EXPIRED
        return self.status


class CredentialRegistry(Versioned):
    """A named, verifiable set of credentials, scoped to one issuer."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    issuer: str = Field(min_length=1, max_length=200)
    entries: list[CredentialEntry] = Field(default_factory=list)

    verified: bool = False
    verified_by: str | None = Field(default=None, max_length=200)
    verified_at: UtcDateTime | None = None
    source_note: str | None = Field(default=None, max_length=500)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def usable(self) -> bool:
        """Only a verified, sourced, non-empty registry may change a score."""
        return self.verified and self.verified_at is not None and bool(self.entries)

    def mark_verified(
        self, *, verified_by: str, source_note: str | None = None
    ) -> CredentialRegistry:
        return self.model_copy(
            update={
                "verified": True,
                "verified_by": verified_by,
                "verified_at": utc_now(),
                "source_note": source_note or self.source_note,
                "updated_at": utc_now(),
            }
        )
