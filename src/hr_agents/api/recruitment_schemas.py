"""Request/response schemas for the recruitment API surface.

Mirrors the contracts in ``docs/api/openapi.yaml`` for documents, jobs,
evaluations, HITL overrides, feedback, and scheduling.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from hr_agents.models import (
    AuditEntry,
    DimensionScore,
    EvaluationFlag,
    FeedbackReport,
    HitlOverride,
    JobSpecification,
    JobStatus,
    Location,
    PolicyDecision,
    PolicyEvaluation,
    Recommendation,
    SchedulingChannel,
    SchedulingPayload,
    ScoreDimension,
    ScoreVector,
    Seniority,
    StrictModel,
    TechnicalEvaluation,
    TimeSlot,
)
from hr_agents.services.recruiting import (
    EvaluationRecord,
    SchedulingProposalRecord,
)

# --- documents -----------------------------------------------------------------


class DocumentUploadResponse(StrictModel):
    document_id: UUID
    sha256: str = Field(min_length=64, max_length=64)
    kind: str
    size_bytes: int = Field(ge=0)


# --- jobs -----------------------------------------------------------------------


class JobCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    seniority: Seniority = Seniority.MID
    description: str = Field(default="", max_length=8000)
    responsibilities: list[str] = Field(default_factory=list)
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    stack: list[str] = Field(default_factory=list)
    min_years_experience: int = Field(default=0, ge=0, le=60)
    dimension_weights: dict[ScoreDimension, float] | None = None
    status: JobStatus = JobStatus.DRAFT


class JobUpdate(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    seniority: Seniority | None = None
    description: str | None = Field(default=None, max_length=8000)
    responsibilities: list[str] | None = None
    must_have_skills: list[str] | None = None
    nice_to_have_skills: list[str] | None = None
    stack: list[str] | None = None
    min_years_experience: int | None = Field(default=None, ge=0, le=60)
    dimension_weights: dict[ScoreDimension, float] | None = None


class JobStatusChange(StrictModel):
    status: JobStatus
    by: str = Field(min_length=1, max_length=200)


class JobView(StrictModel):
    id: UUID
    title: str
    seniority: Seniority
    description: str
    responsibilities: list[str]
    must_have_skills: list[str]
    nice_to_have_skills: list[str]
    stack: list[str]
    min_years_experience: int
    location: Location | None
    dimension_weights: dict[ScoreDimension, float] | None
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    created_by: str | None

    @classmethod
    def from_model(cls, job: JobSpecification) -> JobView:
        return cls(**job.model_dump())


# --- evaluations -----------------------------------------------------------------


class DimensionScoreView(StrictModel):
    dimension: ScoreDimension
    score: float
    weight: float
    rationale: str

    @classmethod
    def from_model(cls, item: DimensionScore) -> DimensionScoreView:
        return cls(
            dimension=item.dimension,
            score=item.score,
            weight=item.weight,
            rationale=item.rationale,
        )


class EvaluationView(StrictModel):
    id: UUID
    application_id: UUID
    candidate_id: UUID
    job_id: UUID | None
    s_tech: float = Field(ge=0.0, le=1.0)
    sigma: float = Field(ge=0.0)
    mean_vector: ScoreVector
    dimension_stddev: dict[ScoreDimension, float]
    weights: dict[ScoreDimension, float]
    breakdown: list[DimensionScoreView]
    flags: list[EvaluationFlag]
    recommendation: Recommendation
    policy: PolicyEvaluation
    policy_version: str
    created_at: datetime

    @classmethod
    def from_record(cls, record: EvaluationRecord) -> EvaluationView:
        evaluation: TechnicalEvaluation = record.evaluation
        return cls(
            id=evaluation.id,
            application_id=record.application_id,
            candidate_id=record.candidate_id,
            job_id=record.job_id,
            s_tech=evaluation.s_tech,
            sigma=evaluation.sigma,
            mean_vector=evaluation.mean_vector,
            dimension_stddev=evaluation.dimension_stddev,
            weights=evaluation.weights,
            breakdown=[DimensionScoreView.from_model(item) for item in evaluation.breakdown],
            flags=evaluation.flags,
            recommendation=evaluation.recommendation,
            policy=record.policy,
            policy_version=evaluation.policy_version,
            created_at=evaluation.created_at,
        )


# --- overrides --------------------------------------------------------------------


class OverrideCreate(StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=200)
    reviewer_role: str = Field(min_length=1, max_length=60)
    override_decision: PolicyDecision
    reason_code: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


class OverrideView(StrictModel):
    evaluation_id: str
    reviewer_id: str
    reviewer_role: str
    override_decision: PolicyDecision
    reason_code: str
    notes: str | None
    decided_at: datetime

    @classmethod
    def from_model(cls, override: HitlOverride) -> OverrideView:
        return cls(**override.model_dump())


class AuditReceipt(StrictModel):
    entry_id: UUID
    seq: int
    entry_hash: str = Field(min_length=64, max_length=64)
    prev_hash: str | None
    created_at: datetime

    @classmethod
    def from_entry(cls, entry: AuditEntry) -> AuditReceipt:
        return cls(
            entry_id=entry.entry_id,
            seq=entry.seq,
            entry_hash=entry.entry_hash,
            prev_hash=entry.prev_hash,
            created_at=entry.created_at,
        )


# --- feedback -----------------------------------------------------------------------


class FeedbackStrengthView(StrictModel):
    dimension: ScoreDimension
    text: str


class FeedbackGrowthView(StrictModel):
    dimension: ScoreDimension
    text: str


class FeedbackView(StrictModel):
    candidate_id: UUID
    candidate_name: str
    job_title: str
    language: str
    summary: str
    strengths: list[FeedbackStrengthView]
    growth_areas: list[FeedbackGrowthView]
    process_note: str
    correction_notice: str
    generated_at: datetime

    @classmethod
    def from_report(
        cls, candidate_id: UUID, report: FeedbackReport, *, generated_at: datetime
    ) -> FeedbackView:
        return cls(
            candidate_id=candidate_id,
            candidate_name=report.candidate_name,
            job_title=report.job_title,
            language=report.language,
            summary=report.summary,
            strengths=[
                FeedbackStrengthView(dimension=item.dimension, text=item.text)
                for item in report.strengths
            ],
            growth_areas=[
                FeedbackGrowthView(dimension=item.dimension, text=item.text)
                for item in report.growth_areas
            ],
            process_note=report.process_note,
            correction_notice=report.correction_notice,
            generated_at=generated_at,
        )


# --- scheduling ----------------------------------------------------------------------


class AvailabilitySet(StrictModel):
    """Ops endpoint payload: register interviewer free slots (calendar feeds later)."""

    interviewer_id: UUID
    slots: list[TimeSlot] = Field(default_factory=list)
    by: str = Field(min_length=1, max_length=200)


class SchedulingProposalRequest(StrictModel):
    candidate_id: UUID
    job_id: UUID
    interviewer_ids: list[UUID] = Field(min_length=1)
    requested_channels: list[SchedulingChannel] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)
    created_by: str = Field(default="system", max_length=200)


class SchedulingProposalView(StrictModel):
    id: UUID
    payload: SchedulingPayload
    requires_human_approval: bool
    needs_human_reconciliation: bool
    created_by: str
    created_at: datetime

    @classmethod
    def from_record(cls, record: SchedulingProposalRecord) -> SchedulingProposalView:
        return cls(
            id=record.id,
            payload=record.payload,
            requires_human_approval=record.requires_human_approval,
            needs_human_reconciliation=record.needs_human_reconciliation,
            created_by=record.created_by,
            created_at=record.created_at,
        )
