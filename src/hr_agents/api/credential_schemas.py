"""Request/response schemas for credential registries."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field

from hr_agents.models import (
    CredentialEntry,
    CredentialRegistry,
    StrictModel,
    UtcDateTime,
    VerificationStatus,
)


class CredentialEntryInput(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    status: VerificationStatus = VerificationStatus.VERIFIED
    credential_id: str | None = Field(default=None, max_length=200)
    expires_on: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class CredentialEntryView(StrictModel):
    name: str
    status: VerificationStatus
    credential_id: str | None
    expires_on: date | None
    notes: str | None

    @classmethod
    def from_model(cls, entry: CredentialEntry) -> CredentialEntryView:
        return cls(
            name=entry.name,
            status=entry.status,
            credential_id=entry.credential_id,
            expires_on=entry.expires_on,
            notes=entry.notes,
        )


class CredentialRegistryCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    issuer: str = Field(min_length=1, max_length=200)


class CredentialRegistryView(StrictModel):
    id: UUID
    name: str
    issuer: str
    entries: list[CredentialEntryView]
    verified: bool
    verified_by: str | None
    verified_at: UtcDateTime | None
    source_note: str | None
    updated_at: UtcDateTime
    usable: bool

    @classmethod
    def from_model(cls, registry: CredentialRegistry) -> CredentialRegistryView:
        return cls(
            id=registry.id,
            name=registry.name,
            issuer=registry.issuer,
            entries=[CredentialEntryView.from_model(entry) for entry in registry.entries],
            verified=registry.verified,
            verified_by=registry.verified_by,
            verified_at=registry.verified_at,
            source_note=registry.source_note,
            updated_at=registry.updated_at,
            usable=registry.usable,
        )


class CredentialEntriesUpdate(StrictModel):
    entries: list[CredentialEntryInput]


class CredentialVerifyRequest(StrictModel):
    source_note: str = Field(
        min_length=1,
        max_length=500,
        description="Where the verified rows came from (issuer page, date, reference).",
    )
