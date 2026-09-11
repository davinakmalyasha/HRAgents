"""Growth domain models — review cycles, form collection, goal tracking.

Rules encoded here:

- **Agents draft, humans decide.** Review summaries carry an explicit agent
  draft field; the final text exists only after a named human finalizes it.
  There is no path from agent draft to ``FINALIZED`` without a human actor.
- **No hardcoded rating scales.** Each cycle carries its operator-set scale
  (``rating_scale_min``/``rating_scale_max``); submissions are validated
  against it in the service.
- **Goals are light.** Progress is a percentage plus an append-only update log;
  completion/cancellation are human actions.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from hr_agents.models.approval import ApproverRole
from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class ReviewCycleKind(StrEnum):
    ANNUAL = "annual"
    MID_YEAR = "mid_year"
    QUARTERLY = "quarterly"
    PROBATION = "probation"
    AD_HOC = "ad_hoc"


class ReviewCycleStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"  # forms being collected
    REVIEWING = "reviewing"  # submissions in, summaries being finalized
    COMPLETED = "completed"
    CANCELLED = "cancelled"


CYCLE_TRANSITIONS: dict[ReviewCycleStatus, frozenset[ReviewCycleStatus]] = {
    ReviewCycleStatus.DRAFT: frozenset({ReviewCycleStatus.ACTIVE, ReviewCycleStatus.CANCELLED}),
    ReviewCycleStatus.ACTIVE: frozenset({ReviewCycleStatus.REVIEWING, ReviewCycleStatus.CANCELLED}),
    ReviewCycleStatus.REVIEWING: frozenset(
        {ReviewCycleStatus.COMPLETED, ReviewCycleStatus.ACTIVE, ReviewCycleStatus.CANCELLED}
    ),
    ReviewCycleStatus.COMPLETED: frozenset(),
    ReviewCycleStatus.CANCELLED: frozenset(),
}


class AssignmentStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    SKIPPED = "skipped"


class SummaryStatus(StrEnum):
    PENDING_REVIEW = "pending_review"  # agent draft awaiting a human edit/finalize
    FINALIZED = "finalized"


class GoalStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReviewCycle(StrictModel):
    """One review round with an operator-set rating scale."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    kind: ReviewCycleKind = ReviewCycleKind.ANNUAL
    period_start: date
    period_end: date

    status: ReviewCycleStatus = ReviewCycleStatus.DRAFT
    rating_scale_min: float = Field(default=1.0)
    rating_scale_max: float = Field(default=5.0)
    submission_due_on: date | None = None
    description: str = Field(default="", max_length=2000)

    created_by: str = Field(min_length=1, max_length=200)
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate(self) -> ReviewCycle:
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot precede period_start")
        if self.rating_scale_max <= self.rating_scale_min:
            raise ValueError("rating_scale_max must exceed rating_scale_min")
        return self

    def can_transition_to(self, target: ReviewCycleStatus) -> bool:
        return target in CYCLE_TRANSITIONS[self.status]


class ReviewAssignment(StrictModel):
    """One reviewer's form for one employee in a cycle."""

    id: UUID = Field(default_factory=uuid4)
    cycle_id: UUID
    employee_id: UUID
    reviewer_id: str = Field(
        min_length=1,
        max_length=200,
        description="Named reviewer (employee id or external name).",
    )
    reviewer_role: ApproverRole = ApproverRole.MANAGER

    status: AssignmentStatus = AssignmentStatus.PENDING
    due_on: date | None = None

    ratings: dict[str, float] = Field(
        default_factory=dict,
        description="Operator-defined dimension keys (e.g. 'delivery') → rating value.",
    )
    comments: str = Field(default="", max_length=4000)

    submitted_by: str | None = Field(default=None, max_length=200)
    submitted_at: UtcDateTime | None = None
    skipped_by: str | None = Field(default=None, max_length=200)
    skipped_at: UtcDateTime | None = None
    skip_reason: str | None = Field(default=None, max_length=500)

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def terminal(self) -> bool:
        return self.status is not AssignmentStatus.PENDING


class ReviewSummary(StrictModel):
    """Per-employee summary: agent draft → human final text."""

    id: UUID = Field(default_factory=uuid4)
    cycle_id: UUID
    employee_id: UUID

    status: SummaryStatus = SummaryStatus.PENDING_REVIEW
    agent_draft: str = Field(default="", max_length=10000)
    draft_by: str | None = Field(default=None, max_length=200)
    draft_created_at: UtcDateTime | None = None

    final_text: str | None = Field(default=None, max_length=10000)
    finalized_by: str | None = Field(default=None, max_length=200)
    finalized_at: UtcDateTime | None = None

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _validate(self) -> ReviewSummary:
        if self.status is SummaryStatus.FINALIZED and (
            self.final_text is None or self.finalized_by is None or self.finalized_at is None
        ):
            raise ValueError("finalized summaries require final_text, finalized_by, finalized_at")
        return self


class GoalUpdate(StrictModel):
    """One append-only progress check-in."""

    progress_percent: float = Field(ge=0.0, le=100.0)
    note: str = Field(default="", max_length=1000)
    by: str = Field(min_length=1, max_length=200)
    at: UtcDateTime = Field(default_factory=utc_now)


class Goal(StrictModel):
    """A light OKR-style goal with a progress log."""

    id: UUID = Field(default_factory=uuid4)
    employee_id: UUID
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    metric: str | None = Field(default=None, max_length=200, description="Target/measure text.")
    cycle_id: UUID | None = None

    status: GoalStatus = GoalStatus.DRAFT
    progress_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    start_on: date | None = None
    due_on: date | None = None

    created_by: str = Field(min_length=1, max_length=200)
    updates: list[GoalUpdate] = Field(default_factory=list)

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def open(self) -> bool:
        return self.status in {GoalStatus.DRAFT, GoalStatus.ACTIVE}

    def is_overdue(self, *, as_of: date | None = None) -> bool:
        if not self.open or self.due_on is None:
            return False
        return self.due_on < (as_of or date.today())


class GrowthReminder(StrictModel):
    """A reminder the service created (task id + what it is about)."""

    kind: str = Field(min_length=1, max_length=60)
    task_id: UUID
    subject_id: UUID
    detail: str = Field(default="", max_length=500)
