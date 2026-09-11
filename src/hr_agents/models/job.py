"""Job specification models — the reference against which candidates are scored."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.candidate import Location
from hr_agents.models.common import StrictModel, UtcDateTime, utc_now
from hr_agents.models.evaluation import DEFAULT_DIMENSION_WEIGHTS, ScoreDimension


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"


class JobStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    PAUSED = "paused"
    CLOSED = "closed"


class JobSpecification(StrictModel):
    """A structured, scoreable job definition.

    Dimension weights override the platform defaults per role; when provided,
    they must be non-negative and sum to 1.0 (tolerance 1e-3).
    """

    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1)
    seniority: Seniority = Seniority.MID
    description: str = Field(default="", max_length=8000)

    responsibilities: list[str] = Field(default_factory=list)
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    stack: list[str] = Field(default_factory=list)
    min_years_experience: int = Field(default=0, ge=0, le=60)

    location: Location | None = None
    dimension_weights: dict[ScoreDimension, float] | None = None

    status: JobStatus = JobStatus.DRAFT
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)
    created_by: str | None = None

    @model_validator(mode="after")
    def _validate_weights(self) -> JobSpecification:
        if self.dimension_weights is None:
            return self
        for dimension, weight in self.dimension_weights.items():
            if weight < 0:
                raise ValueError(f"weight for {dimension} must be non-negative")
        total = sum(self.dimension_weights.values())
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"dimension weights must sum to 1.0 (got {total:.6f})")
        return self

    def effective_weights(self) -> dict[ScoreDimension, float]:
        """Return the weights to use for scoring this role."""
        if self.dimension_weights:
            return dict(self.dimension_weights)
        return dict(DEFAULT_DIMENSION_WEIGHTS)
