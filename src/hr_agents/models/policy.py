"""Policy domain models — automation boundaries and HITL decisions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class PolicyDecision(StrEnum):
    """Which path a candidate's evaluation is routed to."""

    AUTO_SCHEDULE = "auto_schedule"
    HITL_SOFT_REJECTION = "hitl_soft_rejection"
    HITL_ANOMALY = "hitl_anomaly"
    HITL_CALENDAR = "hitl_calendar"
    HITL_MANUAL = "hitl_manual"
    REJECT_AUTO = "reject_auto"


class PolicyThresholds(StrictModel):
    """Snapshot of the thresholds used for a policy evaluation (audit record)."""

    auto_schedule_min_score: float = Field(default=0.85, ge=0.0, le=1.0)
    auto_schedule_max_variance: float = Field(default=0.05, ge=0.0, le=1.0)
    soft_rejection_floor: float = Field(default=0.70, ge=0.0, le=1.0)
    min_interviewer_slots: int = Field(default=2, ge=0)


class PolicyEvaluation(StrictModel):
    """Result of applying policy thresholds to a technical evaluation."""

    decision: PolicyDecision
    reasons: list[str] = Field(default_factory=list)
    thresholds: PolicyThresholds = Field(default_factory=PolicyThresholds)
    evaluated_at: UtcDateTime = Field(default_factory=utc_now)


class HitlOverride(StrictModel):
    """A named human sign-off or course correction on a gated decision."""

    evaluation_id: str
    reviewer_id: str
    reviewer_role: str
    override_decision: PolicyDecision
    reason_code: str
    notes: str | None = Field(default=None, max_length=2000)
    decided_at: UtcDateTime = Field(default_factory=utc_now)
