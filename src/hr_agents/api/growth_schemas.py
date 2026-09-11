"""Growth API schemas."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field

from hr_agents.models import (
    ApproverRole,
    AssignmentStatus,
    Goal,
    GoalStatus,
    GoalUpdate,
    GrowthReminder,
    ReviewAssignment,
    ReviewCycle,
    ReviewCycleKind,
    ReviewCycleStatus,
    ReviewSummary,
    StrictModel,
    SummaryStatus,
    UtcDateTime,
)

# --- cycles ------------------------------------------------------------------


class CycleCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    period_start: date
    period_end: date
    created_by: str = Field(min_length=1, max_length=200)
    kind: ReviewCycleKind = ReviewCycleKind.ANNUAL
    rating_scale_min: float = 1.0
    rating_scale_max: float = 5.0
    submission_due_on: date | None = None
    description: str = Field(default="", max_length=2000)


class CycleAction(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500)


class CycleView(StrictModel):
    id: UUID
    name: str
    kind: ReviewCycleKind
    period_start: date
    period_end: date
    status: ReviewCycleStatus
    rating_scale_min: float
    rating_scale_max: float
    submission_due_on: date | None
    description: str
    created_by: str
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @classmethod
    def from_model(cls, cycle: ReviewCycle) -> CycleView:
        return cls(**cycle.model_dump())


# --- assignments --------------------------------------------------------------


class AssignmentCreate(StrictModel):
    employee_id: UUID
    reviewer_id: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    reviewer_role: ApproverRole | None = None
    due_on: date | None = None


class AssignmentSubmit(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    ratings: dict[str, float] = Field(min_length=1)
    comments: str = Field(default="", max_length=4000)


class AssignmentSkip(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


class AssignmentView(StrictModel):
    id: UUID
    cycle_id: UUID
    employee_id: UUID
    reviewer_id: str
    reviewer_role: ApproverRole
    status: AssignmentStatus
    due_on: date | None
    ratings: dict[str, float]
    comments: str
    submitted_by: str | None
    submitted_at: UtcDateTime | None
    skipped_by: str | None
    skipped_at: UtcDateTime | None
    skip_reason: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @classmethod
    def from_model(cls, assignment: ReviewAssignment) -> AssignmentView:
        return cls(**assignment.model_dump())


# --- summaries ----------------------------------------------------------------


class SummaryDraft(StrictModel):
    cycle_id: UUID
    employee_id: UUID
    draft_text: str = Field(min_length=1, max_length=10000)
    drafted_by: str = Field(min_length=1, max_length=200)


class SummaryFinalize(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    final_text: str = Field(min_length=1, max_length=10000)


class SummaryView(StrictModel):
    id: UUID
    cycle_id: UUID
    employee_id: UUID
    status: SummaryStatus
    agent_draft: str
    draft_by: str | None
    draft_created_at: UtcDateTime | None
    final_text: str | None
    finalized_by: str | None
    finalized_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @classmethod
    def from_model(cls, summary: ReviewSummary) -> SummaryView:
        return cls(**summary.model_dump())


# --- goals ---------------------------------------------------------------------


class GoalCreate(StrictModel):
    employee_id: UUID
    title: str = Field(min_length=1, max_length=200)
    created_by: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    metric: str | None = Field(default=None, max_length=200)
    cycle_id: UUID | None = None
    start_on: date | None = None
    due_on: date | None = None


class GoalProgress(StrictModel):
    percent: float = Field(ge=0.0, le=100.0)
    by: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=1000)


class GoalAction(StrictModel):
    by: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=1000)
    reason: str | None = Field(default=None, max_length=500)


class GoalUpdateView(StrictModel):
    progress_percent: float
    note: str
    by: str
    at: UtcDateTime

    @classmethod
    def from_model(cls, update: GoalUpdate) -> GoalUpdateView:
        return cls(**update.model_dump())


class GoalView(StrictModel):
    id: UUID
    employee_id: UUID
    title: str
    description: str
    metric: str | None
    cycle_id: UUID | None
    status: GoalStatus
    progress_percent: float
    start_on: date | None
    due_on: date | None
    created_by: str
    updates: list[GoalUpdateView]
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @classmethod
    def from_model(cls, goal: Goal) -> GoalView:
        return cls(
            id=goal.id,
            employee_id=goal.employee_id,
            title=goal.title,
            description=goal.description,
            metric=goal.metric,
            cycle_id=goal.cycle_id,
            status=goal.status,
            progress_percent=goal.progress_percent,
            start_on=goal.start_on,
            due_on=goal.due_on,
            created_by=goal.created_by,
            updates=[GoalUpdateView.from_model(item) for item in goal.updates],
            created_at=goal.created_at,
            updated_at=goal.updated_at,
        )


# --- reminders -------------------------------------------------------------------


class ByActor(StrictModel):
    by: str = Field(min_length=1, max_length=200)


class ReminderView(StrictModel):
    kind: str
    task_id: UUID
    subject_id: UUID
    detail: str

    @classmethod
    def from_model(cls, reminder: GrowthReminder) -> ReminderView:
        return cls(**reminder.model_dump())


class RemindersRun(StrictModel):
    as_of: date | None = None
    window_days: int = Field(default=3, ge=0, le=60)
