"""Evaluation domain models — the deterministic score tensor and its aggregation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from statistics import pstdev
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models.common import EvidenceRef, StrictModel, UtcDateTime, utc_now


class ScoreDimension(StrEnum):
    """The four axes of the evaluation tensor S ∈ [0, 1]^4."""

    TECHNICAL_DEPTH = "technical_depth"
    STACK_ALIGNMENT = "stack_alignment"
    SYSTEMS_LITERACY = "systems_literacy"
    VERIFIABLE_CERTIFICATIONS = "verifiable_certifications"


def _default_weights() -> dict[ScoreDimension, float]:
    return {
        ScoreDimension.TECHNICAL_DEPTH: 0.40,
        ScoreDimension.STACK_ALIGNMENT: 0.30,
        ScoreDimension.SYSTEMS_LITERACY: 0.20,
        ScoreDimension.VERIFIABLE_CERTIFICATIONS: 0.10,
    }


DEFAULT_DIMENSION_WEIGHTS = _default_weights()


class ScoreVector(StrictModel):
    """Per-dimension scores, each bounded to [0, 1]."""

    technical_depth: float = Field(ge=0.0, le=1.0)
    stack_alignment: float = Field(ge=0.0, le=1.0)
    systems_literacy: float = Field(ge=0.0, le=1.0)
    verifiable_certifications: float = Field(ge=0.0, le=1.0)

    def as_mapping(self) -> dict[ScoreDimension, float]:
        return {
            ScoreDimension.TECHNICAL_DEPTH: self.technical_depth,
            ScoreDimension.STACK_ALIGNMENT: self.stack_alignment,
            ScoreDimension.SYSTEMS_LITERACY: self.systems_literacy,
            ScoreDimension.VERIFIABLE_CERTIFICATIONS: self.verifiable_certifications,
        }

    def weighted_mean(self, weights: Mapping[ScoreDimension, float]) -> float:
        """Weighted mean over present dimensions.

        Weights are normalized over the dimensions supplied, so callers may
        provide partial weights.
        """
        total = 0.0
        total_weight = 0.0
        for dimension, value in self.as_mapping().items():
            weight = float(weights.get(dimension, 0.0))
            if weight < 0:
                raise ValueError(f"weight for {dimension} must be non-negative")
            total += value * weight
            total_weight += weight
        if total_weight == 0.0:
            raise ValueError("at least one positive dimension weight is required")
        return total / total_weight


class DimensionScore(StrictModel):
    """A single dimension's score with its rationale and supporting evidence."""

    dimension: ScoreDimension
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    rationale: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ScoringRun(StrictModel):
    """One independent extraction-and-scoring pass (used to measure variance)."""

    run_index: int = Field(ge=0)
    extraction_id: UUID
    vector: ScoreVector
    created_at: UtcDateTime = Field(default_factory=utc_now)


class EvaluationFlag(StrEnum):
    """Signals that route an evaluation to a human, regardless of score."""

    ANOMALY_EXPERIENCE_FORMAT = "anomaly_experience_format"
    LOW_CONFIDENCE_EXTRACTION = "low_confidence_extraction"
    INCONSISTENT_RUNS = "inconsistent_runs"
    CERTIFICATION_MISMATCH = "certification_mismatch"
    INJECTION_SUSPECTED = "injection_suspected"
    CALENDAR_CONSTRAINT = "calendar_constraint"


class Recommendation(StrEnum):
    """Outcome of applying policy thresholds to an aggregate evaluation."""

    AUTO_SCHEDULE = "auto_schedule"
    HUMAN_REVIEW = "human_review"
    REJECT_REQUIRES_SIGNOFF = "reject_requires_signoff"
    REJECT = "reject"


class TechnicalEvaluation(StrictModel):
    """Aggregate deterministic evaluation across k independent scoring runs."""

    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    job_id: UUID | None = None

    runs: list[ScoringRun] = Field(min_length=1)
    mean_vector: ScoreVector
    dimension_stddev: dict[ScoreDimension, float] = Field(default_factory=dict)
    s_tech: float = Field(ge=0.0, le=1.0)
    sigma: float = Field(ge=0.0)

    weights: dict[ScoreDimension, float] = Field(default_factory=_default_weights)
    breakdown: list[DimensionScore] = Field(default_factory=list)
    flags: list[EvaluationFlag] = Field(default_factory=list)
    recommendation: Recommendation
    policy_version: str = "1.0"
    created_at: UtcDateTime = Field(default_factory=utc_now)


def aggregate_runs(
    runs: Sequence[ScoringRun],
    weights: Mapping[ScoreDimension, float] | None = None,
) -> tuple[ScoreVector, dict[ScoreDimension, float], float, float]:
    """Aggregate k scoring runs deterministically.

    Returns ``(mean_vector, dimension_stddev, s_tech, sigma)`` where ``s_tech``
    is the weighted mean over run means and ``sigma`` is the population standard
    deviation of the per-run weighted means.
    """
    if not runs:
        raise ValueError("at least one scoring run is required")

    effective_weights = dict(weights or DEFAULT_DIMENSION_WEIGHTS)

    per_dimension: dict[ScoreDimension, list[float]] = {
        dimension: [] for dimension in ScoreDimension
    }
    per_run_weighted: list[float] = []

    for run in runs:
        mapping = run.vector.as_mapping()
        for dimension, value in mapping.items():
            per_dimension[dimension].append(value)
        per_run_weighted.append(run.vector.weighted_mean(effective_weights))

    mean_vector = ScoreVector(
        technical_depth=sum(per_dimension[ScoreDimension.TECHNICAL_DEPTH])
        / len(per_dimension[ScoreDimension.TECHNICAL_DEPTH]),
        stack_alignment=sum(per_dimension[ScoreDimension.STACK_ALIGNMENT])
        / len(per_dimension[ScoreDimension.STACK_ALIGNMENT]),
        systems_literacy=sum(per_dimension[ScoreDimension.SYSTEMS_LITERACY])
        / len(per_dimension[ScoreDimension.SYSTEMS_LITERACY]),
        verifiable_certifications=sum(per_dimension[ScoreDimension.VERIFIABLE_CERTIFICATIONS])
        / len(per_dimension[ScoreDimension.VERIFIABLE_CERTIFICATIONS]),
    )

    dimension_stddev = {
        dimension: (pstdev(values) if len(values) > 1 else 0.0)
        for dimension, values in per_dimension.items()
    }
    s_tech = mean_vector.weighted_mean(effective_weights)
    sigma = pstdev(per_run_weighted) if len(per_run_weighted) > 1 else 0.0

    return mean_vector, dimension_stddev, s_tech, sigma
