"""Per-job score distributions, computed from registered evaluations.

These are monitoring shapes, not demographic metrics. HRAgents does not store
or score protected attributes, so no report here can compute demographic
parity; what it can show is whether scores, routing and flags drift for a job.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from hr_agents.models.common import StrictModel, UtcDateTime


class ScoreBin(StrictModel):
    """One half-open interval of the weighted total: ``[low, high)``."""

    low: float = Field(ge=0.0, le=1.0)
    high: float = Field(gt=0.0, le=1.0)
    count: int = Field(ge=0)


class JobScoreDistribution(StrictModel):
    job_id: UUID | None = None
    job_title: str
    evaluations: int = Field(ge=0)
    mean: float
    minimum: float
    maximum: float
    bins: list[ScoreBin] = Field(default_factory=list)
    recommendations: dict[str, int] = Field(default_factory=dict)
    requires_human: int = Field(ge=0)
    flagged: int = Field(ge=0)


class ScoreDistributionReport(StrictModel):
    since: UtcDateTime
    until: UtcDateTime
    evaluations: int = Field(ge=0)
    truncated: bool = False
    jobs: list[JobScoreDistribution] = Field(default_factory=list)
    note: str
