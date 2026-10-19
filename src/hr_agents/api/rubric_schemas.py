"""Request/response schemas for the rubric registry."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from hr_agents.models import JobFamily, RubricVersion, StrictModel


class RubricVersionView(StrictModel):
    """One stored version, including the payload it will score with."""

    id: UUID
    family: JobFamily
    revision: int = Field(ge=1)
    digest: str
    active: bool
    verified_by: str | None
    verified_at: datetime | None
    verified_note: str | None
    created_by: str
    created_at: datetime
    template: dict[str, object]

    @classmethod
    def from_model(cls, record: RubricVersion) -> RubricVersionView:
        return cls(
            id=record.id,
            family=record.family,
            revision=record.revision,
            digest=record.digest,
            active=record.active,
            verified_by=record.verified_by,
            verified_at=record.verified_at,
            verified_note=record.verified_note,
            created_by=record.created_by,
            created_at=record.created_at,
            template=record.template,
        )


class RubricFamilyView(StrictModel):
    """Which rubric currently scores a family, and where it comes from."""

    family: JobFamily
    source: Literal["code", "registry"]
    revision: int | None = None
    digest: str
    verified_by: str | None = None
    verified_at: datetime | None = None


class RubricVerifyRequest(StrictModel):
    source_note: str = Field(min_length=1, max_length=500)
