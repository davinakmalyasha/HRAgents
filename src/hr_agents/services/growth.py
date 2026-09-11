"""Growth service — review cycles, form collection, summary drafts, light goals.

Deterministic: no LLM. Agents may draft summary text and raise reminders;
humans submit forms, finalize summaries, and complete goals. The service is
the enforcement point for both rules and records everything on the audit chain.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from hr_agents.models import (
    CYCLE_TRANSITIONS,
    ActorType,
    ApproverRole,
    AssignmentStatus,
    AuditActor,
    Goal,
    GoalStatus,
    GoalUpdate,
    GrowthReminder,
    ReviewAssignment,
    ReviewCycle,
    ReviewCycleKind,
    ReviewCycleStatus,
    ReviewSummary,
    SummaryStatus,
    TaskSource,
    utc_now,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import GrowthStore
from hr_agents.services.tasks import TaskEngine

DEFAULT_REMINDER_WINDOW_DAYS = 3


class GrowthError(RuntimeError):
    """Raised for invalid growth operations."""


def _actor_type(actor_id: str) -> ActorType:
    if actor_id.startswith("agent:"):
        return ActorType.AGENT
    if actor_id == "system" or actor_id.startswith("system:"):
        return ActorType.SYSTEM
    return ActorType.HUMAN


class GrowthService:
    """Review cycles, assignments, summaries, and goals."""

    def __init__(
        self,
        store: GrowthStore | None = None,
        *,
        tasks: TaskEngine,
        audit: AuditChain | None = None,
    ) -> None:
        self._store = store or GrowthStore()
        self._tasks = tasks
        self._audit = audit or AuditChain()

    # --- cycles -----------------------------------------------------------

    def create_cycle(
        self,
        *,
        name: str,
        period_start: date,
        period_end: date,
        created_by: str,
        kind: ReviewCycleKind = ReviewCycleKind.ANNUAL,
        rating_scale_min: float = 1.0,
        rating_scale_max: float = 5.0,
        submission_due_on: date | None = None,
        description: str = "",
    ) -> ReviewCycle:
        self._require_human(created_by, "create a review cycle")
        cycle = ReviewCycle(
            name=name,
            kind=kind,
            period_start=period_start,
            period_end=period_end,
            rating_scale_min=rating_scale_min,
            rating_scale_max=rating_scale_max,
            submission_due_on=submission_due_on,
            description=description,
            created_by=created_by,
        )
        self._store.add_cycle(cycle)
        self._record(
            cycle,
            action="growth.cycle_created",
            actor_id=created_by,
            payload={"kind": kind.value, "name": name},
        )
        return cycle

    def get_cycle(self, cycle_id: UUID) -> ReviewCycle:
        cycle = self._store.get_cycle(cycle_id)
        if cycle is None:
            raise GrowthError(f"unknown review cycle {cycle_id}")
        return cycle

    def list_cycles(self, *, status: ReviewCycleStatus | None = None) -> list[ReviewCycle]:
        cycles = self._store.list_cycles()
        if status is not None:
            cycles = [cycle for cycle in cycles if cycle.status is status]
        return cycles

    def _transition_cycle(
        self,
        cycle_id: UUID,
        *,
        target: ReviewCycleStatus,
        by: str,
        action: str,
        payload: dict[str, object] | None = None,
    ) -> ReviewCycle:
        self._require_human(by, "transition a review cycle")
        cycle = self.get_cycle(cycle_id)
        if target not in CYCLE_TRANSITIONS[cycle.status]:
            raise GrowthError(f"cannot move cycle from {cycle.status.value} to {target.value}")
        updated = cycle.model_copy(update={"status": target, "updated_at": utc_now()})
        self._store.save_cycle(updated)
        self._record(updated, action=action, actor_id=by, payload=payload or {})
        return updated

    def activate_cycle(self, cycle_id: UUID, *, by: str) -> ReviewCycle:
        """Open the cycle for form collection; requires at least one assignment."""
        self.get_cycle(cycle_id)
        if not self.list_assignments(cycle_id):
            raise GrowthError("add at least one assignment before activating the cycle")
        return self._transition_cycle(
            cycle_id, target=ReviewCycleStatus.ACTIVE, by=by, action="growth.cycle_activated"
        )

    def advance_to_reviewing(self, cycle_id: UUID, *, by: str) -> ReviewCycle:
        self.get_cycle(cycle_id)
        pending = [item for item in self.list_assignments(cycle_id) if not item.terminal]
        if pending:
            raise GrowthError(f"{len(pending)} assignments still pending; submit or skip first")
        return self._transition_cycle(
            cycle_id,
            target=ReviewCycleStatus.REVIEWING,
            by=by,
            action="growth.cycle_reviewing",
        )

    def close_cycle(self, cycle_id: UUID, *, by: str) -> ReviewCycle:
        """Complete the cycle: no pending forms, all existing summaries finalized."""
        self.get_cycle(cycle_id)
        pending = [item for item in self.list_assignments(cycle_id) if not item.terminal]
        if pending:
            raise GrowthError(f"{len(pending)} assignments still pending; submit or skip first")
        open_summaries = [
            summary
            for summary in self.list_summaries(cycle_id)
            if summary.status is not SummaryStatus.FINALIZED
        ]
        if open_summaries:
            raise GrowthError(
                f"{len(open_summaries)} summaries await human finalization; finalize first"
            )
        return self._transition_cycle(
            cycle_id, target=ReviewCycleStatus.COMPLETED, by=by, action="growth.cycle_completed"
        )

    def cancel_cycle(self, cycle_id: UUID, *, by: str, reason: str) -> ReviewCycle:
        if not reason.strip():
            raise GrowthError("cancelling a cycle requires a reason")
        return self._transition_cycle(
            cycle_id,
            target=ReviewCycleStatus.CANCELLED,
            by=by,
            action="growth.cycle_cancelled",
            payload={"reason": reason},
        )

    # --- assignments -------------------------------------------------------

    def add_assignment(
        self,
        cycle_id: UUID,
        *,
        employee_id: UUID,
        reviewer_id: str,
        created_by: str,
        reviewer_role: ApproverRole | None = None,
        due_on: date | None = None,
    ) -> ReviewAssignment:
        cycle = self.get_cycle(cycle_id)
        if cycle.status not in {ReviewCycleStatus.DRAFT, ReviewCycleStatus.ACTIVE}:
            raise GrowthError(f"cycle is {cycle.status.value}; assignments are closed")
        duplicate = next(
            (
                item
                for item in self.list_assignments(cycle_id)
                if item.employee_id == employee_id and item.reviewer_id == reviewer_id
            ),
            None,
        )
        if duplicate is not None:
            raise GrowthError("this reviewer already has an assignment for the employee")

        assignment = ReviewAssignment(
            cycle_id=cycle_id,
            employee_id=employee_id,
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role or ApproverRole.MANAGER,
            due_on=due_on or cycle.submission_due_on,
        )
        self._store.add_assignment(assignment)
        self._record(
            cycle,
            action="growth.assignment_created",
            actor_id=created_by,
            payload={
                "assignment_id": str(assignment.id),
                "employee_id": str(employee_id),
                "reviewer_id": reviewer_id,
            },
        )
        return assignment

    def get_assignment(self, assignment_id: UUID) -> ReviewAssignment:
        assignment = self._store.get_assignment(assignment_id)
        if assignment is None:
            raise GrowthError(f"unknown review assignment {assignment_id}")
        return assignment

    def list_assignments(self, cycle_id: UUID) -> list[ReviewAssignment]:
        return [item for item in self._store.list_assignments() if item.cycle_id == cycle_id]

    def assignments_for_reviewer(self, reviewer_id: str) -> list[ReviewAssignment]:
        return [
            item
            for item in self._store.list_assignments()
            if item.reviewer_id == reviewer_id and not item.terminal
        ]

    def submit_assignment(
        self,
        assignment_id: UUID,
        *,
        by: str,
        ratings: dict[str, float],
        comments: str = "",
    ) -> ReviewAssignment:
        """Submit a reviewer's form. Humans only; ratings validated against the scale."""
        self._require_human(by, "submit a review form")
        assignment = self.get_assignment(assignment_id)
        if assignment.status is not AssignmentStatus.PENDING:
            raise GrowthError(f"assignment is {assignment.status.value}; cannot submit")
        cycle = self.get_cycle(assignment.cycle_id)
        if cycle.status is not ReviewCycleStatus.ACTIVE:
            raise GrowthError(f"cycle is {cycle.status.value}; forms are closed")
        if not ratings:
            raise GrowthError("a review submission requires at least one rating")
        for dimension, value in ratings.items():
            if not dimension.strip():
                raise GrowthError("rating dimension keys cannot be blank")
            if not cycle.rating_scale_min <= value <= cycle.rating_scale_max:
                raise GrowthError(
                    f"rating for {dimension!r} is {value}; scale is "
                    f"{cycle.rating_scale_min}-{cycle.rating_scale_max}"
                )

        updated = assignment.model_copy(
            update={
                "status": AssignmentStatus.SUBMITTED,
                "ratings": ratings,
                "comments": comments,
                "submitted_by": by,
                "submitted_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        self._store.save_assignment(updated)
        self._record(
            cycle,
            action="growth.assignment_submitted",
            actor_id=by,
            payload={"assignment_id": str(updated.id), "dimensions": sorted(ratings)},
        )
        return updated

    def skip_assignment(self, assignment_id: UUID, *, by: str, reason: str) -> ReviewAssignment:
        """Skip a form (e.g., reviewer left). Human decision with a reason."""
        self._require_human(by, "skip a review form")
        if not reason.strip():
            raise GrowthError("skipping an assignment requires a reason")
        assignment = self.get_assignment(assignment_id)
        if assignment.status is not AssignmentStatus.PENDING:
            raise GrowthError(f"assignment is {assignment.status.value}; cannot skip")
        cycle = self.get_cycle(assignment.cycle_id)
        updated = assignment.model_copy(
            update={
                "status": AssignmentStatus.SKIPPED,
                "skip_reason": reason,
                "skipped_by": by,
                "skipped_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        self._store.save_assignment(updated)
        self._record(
            cycle,
            action="growth.assignment_skipped",
            actor_id=by,
            payload={"assignment_id": str(updated.id), "reason": reason},
        )
        return updated

    def submitted_ratings(self, cycle_id: UUID, employee_id: UUID) -> dict[str, list[float]]:
        """Collected ratings per dimension (inputs for a summary draft)."""
        collected: dict[str, list[float]] = {}
        for item in self.list_assignments(cycle_id):
            if item.employee_id != employee_id or item.status is not AssignmentStatus.SUBMITTED:
                continue
            for dimension, value in item.ratings.items():
                collected.setdefault(dimension, []).append(value)
        return collected

    # --- summaries ---------------------------------------------------------

    def draft_summary(
        self,
        cycle_id: UUID,
        employee_id: UUID,
        *,
        draft_text: str,
        drafted_by: str,
    ) -> ReviewSummary:
        """Create or refresh an agent/human draft. Never finalizes."""
        cycle = self.get_cycle(cycle_id)
        if cycle.status not in {ReviewCycleStatus.ACTIVE, ReviewCycleStatus.REVIEWING}:
            raise GrowthError(f"cycle is {cycle.status.value}; summaries are closed")
        submitted = [
            item
            for item in self.list_assignments(cycle_id)
            if item.employee_id == employee_id and item.status is AssignmentStatus.SUBMITTED
        ]
        if not submitted:
            raise GrowthError(
                "no submitted review forms for this employee; a draft must be grounded in them"
            )
        if not draft_text.strip():
            raise GrowthError("draft text cannot be empty")

        existing = next(
            (item for item in self.list_summaries(cycle_id) if item.employee_id == employee_id),
            None,
        )
        if existing is not None:
            if existing.status is SummaryStatus.FINALIZED:
                raise GrowthError("summary is finalized; it can no longer be re-drafted")
            updated = existing.model_copy(
                update={
                    "agent_draft": draft_text,
                    "draft_by": drafted_by,
                    "draft_created_at": utc_now(),
                    "updated_at": utc_now(),
                }
            )
            self._store.save_summary(updated)
            summary = updated
        else:
            summary = ReviewSummary(
                cycle_id=cycle_id,
                employee_id=employee_id,
                status=SummaryStatus.PENDING_REVIEW,
                agent_draft=draft_text,
                draft_by=drafted_by,
                draft_created_at=utc_now(),
            )
            self._store.add_summary(summary)

        self._record(
            cycle,
            action="growth.summary_drafted",
            actor_id=drafted_by,
            payload={"summary_id": str(summary.id), "employee_id": str(employee_id)},
        )
        return summary

    def get_summary(self, summary_id: UUID) -> ReviewSummary:
        summary = self._store.get_summary(summary_id)
        if summary is None:
            raise GrowthError(f"unknown review summary {summary_id}")
        return summary

    def list_summaries(self, cycle_id: UUID) -> list[ReviewSummary]:
        return [item for item in self._store.list_summaries() if item.cycle_id == cycle_id]

    def finalize_summary(self, summary_id: UUID, *, by: str, final_text: str) -> ReviewSummary:
        """Human-only finalization. The final text is what gets shared."""
        self._require_human(by, "finalize a review summary")
        if not final_text.strip():
            raise GrowthError("final text cannot be empty")
        summary = self.get_summary(summary_id)
        if summary.status is SummaryStatus.FINALIZED:
            raise GrowthError("summary is already finalized")
        cycle = self.get_cycle(summary.cycle_id)
        updated = summary.model_copy(
            update={
                "status": SummaryStatus.FINALIZED,
                "final_text": final_text,
                "finalized_by": by,
                "finalized_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        self._store.save_summary(updated)
        self._record(
            cycle,
            action="growth.summary_finalized",
            actor_id=by,
            payload={"summary_id": str(updated.id), "employee_id": str(summary.employee_id)},
        )
        return updated

    # --- reminders ---------------------------------------------------------

    def run_reminders(
        self, *, as_of: date | None = None, window_days: int = DEFAULT_REMINDER_WINDOW_DAYS
    ) -> list[GrowthReminder]:
        """Create system tasks for due forms and unfinalized summaries.

        Deduplicated: an open task for the same assignment/summary is not
        duplicated, so this can run daily.
        """
        moment = as_of or date.today()
        horizon = moment + timedelta(days=window_days)
        created: list[GrowthReminder] = []

        for cycle in self.list_cycles():
            if cycle.status is not ReviewCycleStatus.ACTIVE:
                continue
            for assignment in self.list_assignments(cycle.id):
                if assignment.terminal or assignment.due_on is None:
                    continue
                if assignment.due_on > horizon:
                    continue
                if self._tasks.open_for_related(
                    related_subject="review_assignment", related_id=str(assignment.id)
                ):
                    continue
                task = self._tasks.create(
                    title=f"[Review] Submit form for {cycle.name}",
                    created_by="system",
                    description=(
                        f"Reviewer {assignment.reviewer_id} has a pending form. "
                        f"Due {assignment.due_on.isoformat()}."
                    ),
                    assignee_role=assignment.reviewer_role,
                    due_on=assignment.due_on,
                    source=TaskSource.SYSTEM,
                    related_subject="review_assignment",
                    related_id=str(assignment.id),
                )
                created.append(
                    GrowthReminder(
                        kind="assignment_due",
                        task_id=task.id,
                        subject_id=assignment.id,
                        detail=f"due {assignment.due_on.isoformat()}",
                    )
                )

        for cycle in self.list_cycles():
            if cycle.status not in {ReviewCycleStatus.ACTIVE, ReviewCycleStatus.REVIEWING}:
                continue
            for summary in self.list_summaries(cycle.id):
                if summary.status is not SummaryStatus.PENDING_REVIEW:
                    continue
                if self._tasks.open_for_related(
                    related_subject="review_summary", related_id=str(summary.id)
                ):
                    continue
                task = self._tasks.create(
                    title=f"[Review] Finalize summary for {cycle.name}",
                    created_by="system",
                    description=(
                        "An agent draft awaits human editing and finalization before the "
                        "cycle can close."
                    ),
                    due_on=cycle.submission_due_on,
                    source=TaskSource.SYSTEM,
                    related_subject="review_summary",
                    related_id=str(summary.id),
                )
                created.append(
                    GrowthReminder(
                        kind="summary_awaiting_finalize",
                        task_id=task.id,
                        subject_id=summary.id,
                        detail="agent draft awaiting human finalization",
                    )
                )

        return created

    # --- goals --------------------------------------------------------------

    def create_goal(
        self,
        *,
        employee_id: UUID,
        title: str,
        created_by: str,
        description: str = "",
        metric: str | None = None,
        cycle_id: UUID | None = None,
        start_on: date | None = None,
        due_on: date | None = None,
    ) -> Goal:
        self._require_human(created_by, "create a goal")
        if cycle_id is not None:
            self.get_cycle(cycle_id)
        goal = Goal(
            employee_id=employee_id,
            title=title,
            description=description,
            metric=metric,
            cycle_id=cycle_id,
            start_on=start_on,
            due_on=due_on,
            created_by=created_by,
        )
        self._store.add_goal(goal)
        self._record(
            goal,
            action="growth.goal_created",
            actor_id=created_by,
            payload={"employee_id": str(employee_id), "title": title},
        )
        return goal

    def get_goal(self, goal_id: UUID) -> Goal:
        goal = self._store.get_goal(goal_id)
        if goal is None:
            raise GrowthError(f"unknown goal {goal_id}")
        return goal

    def list_goals(
        self, *, employee_id: UUID | None = None, status: GoalStatus | None = None
    ) -> list[Goal]:
        goals = self._store.list_goals()
        if employee_id is not None:
            goals = [goal for goal in goals if goal.employee_id == employee_id]
        if status is not None:
            goals = [goal for goal in goals if goal.status is status]
        return goals

    def activate_goal(self, goal_id: UUID, *, by: str) -> Goal:
        self._require_human(by, "activate a goal")
        goal = self.get_goal(goal_id)
        if goal.status is not GoalStatus.DRAFT:
            raise GrowthError(f"goal is {goal.status.value}; cannot activate")
        updated = goal.model_copy(update={"status": GoalStatus.ACTIVE, "updated_at": utc_now()})
        self._store.save_goal(updated)
        self._record(updated, action="growth.goal_activated", actor_id=by, payload={})
        return updated

    def update_progress(self, goal_id: UUID, *, percent: float, by: str, note: str = "") -> Goal:
        self._require_human(by, "update goal progress")
        goal = self.get_goal(goal_id)
        if not goal.open:
            raise GrowthError(f"goal is {goal.status.value}; cannot update progress")
        if not 0.0 <= percent <= 100.0:
            raise GrowthError("progress must be between 0 and 100")
        updates = [
            *goal.updates,
            GoalUpdate(progress_percent=percent, note=note, by=by),
        ]
        updated = goal.model_copy(
            update={
                "progress_percent": percent,
                "status": GoalStatus.ACTIVE if goal.status is GoalStatus.DRAFT else goal.status,
                "updates": updates,
                "updated_at": utc_now(),
            }
        )
        self._store.save_goal(updated)
        self._record(
            updated,
            action="growth.goal_progress",
            actor_id=by,
            payload={"percent": percent},
        )
        return updated

    def complete_goal(self, goal_id: UUID, *, by: str, note: str = "") -> Goal:
        self._require_human(by, "complete a goal")
        goal = self.get_goal(goal_id)
        if not goal.open:
            raise GrowthError(f"goal is {goal.status.value}; cannot complete")
        updates = [*goal.updates, GoalUpdate(progress_percent=100.0, note=note, by=by)]
        updated = goal.model_copy(
            update={
                "status": GoalStatus.COMPLETED,
                "progress_percent": 100.0,
                "updates": updates,
                "updated_at": utc_now(),
            }
        )
        self._store.save_goal(updated)
        self._record(updated, action="growth.goal_completed", actor_id=by, payload={})
        return updated

    def cancel_goal(self, goal_id: UUID, *, by: str, reason: str) -> Goal:
        self._require_human(by, "cancel a goal")
        if not reason.strip():
            raise GrowthError("cancelling a goal requires a reason")
        goal = self.get_goal(goal_id)
        if not goal.open:
            raise GrowthError(f"goal is {goal.status.value}; cannot cancel")
        updated = goal.model_copy(update={"status": GoalStatus.CANCELLED, "updated_at": utc_now()})
        self._store.save_goal(updated)
        self._record(
            updated, action="growth.goal_cancelled", actor_id=by, payload={"reason": reason}
        )
        return updated

    def overdue_goals(self, *, as_of: date | None = None) -> list[Goal]:
        return [goal for goal in self._store.list_goals() if goal.is_overdue(as_of=as_of)]

    # --- internals -----------------------------------------------------------

    def _require_human(self, actor: str, action: str) -> None:
        if actor.startswith("agent:"):
            raise GrowthError(f"agents cannot {action}; a named human is required")

    def _record(
        self,
        subject: ReviewCycle | ReviewSummary | Goal,
        *,
        action: str,
        actor_id: str,
        payload: dict[str, object],
    ) -> None:
        subject_type = {
            ReviewCycle: "review_cycle",
            ReviewSummary: "review_summary",
            Goal: "goal",
        }[type(subject)]
        self._audit.append(
            actor=AuditActor(actor_type=_actor_type(actor_id), actor_id=actor_id),
            action=action,
            subject_type=subject_type,
            subject_id=str(subject.id),
            payload=payload,
        )
