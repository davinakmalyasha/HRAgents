"""Growth service — review cycles, form collection, summary drafts, light goals.

Deterministic: no LLM. Agents may draft summary text and raise reminders;
humans submit forms, finalize summaries, and complete goals. The service is
the enforcement point for both rules and records everything on the audit chain.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from hr_agents.identity import ActorRef, require_named_human
from hr_agents.models import (
    CYCLE_TRANSITIONS,
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
        actor: ActorRef,
        kind: ReviewCycleKind = ReviewCycleKind.ANNUAL,
        rating_scale_min: float = 1.0,
        rating_scale_max: float = 5.0,
        submission_due_on: date | None = None,
        description: str = "",
    ) -> ReviewCycle:
        actor.require_human("create a review cycle", GrowthError)
        cycle = ReviewCycle(
            created_by=actor.actor_id,
            name=name,
            kind=kind,
            period_start=period_start,
            period_end=period_end,
            rating_scale_min=rating_scale_min,
            rating_scale_max=rating_scale_max,
            submission_due_on=submission_due_on,
            description=description,
        )
        self._store.add_cycle(cycle)
        self._record(
            cycle,
            action="growth.cycle_created",
            actor=actor,
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
        actor: ActorRef,
        action: str,
        payload: dict[str, object] | None = None,
    ) -> ReviewCycle:
        actor.require_human("transition a review cycle", GrowthError)
        cycle = self.get_cycle(cycle_id)
        if target not in CYCLE_TRANSITIONS[cycle.status]:
            raise GrowthError(f"cannot move cycle from {cycle.status.value} to {target.value}")
        updated = cycle.model_copy(update={"status": target, "updated_at": utc_now()})
        self._store.save_cycle(updated)
        self._record(updated, action=action, actor=actor, payload=payload or {})
        return updated

    def activate_cycle(self, cycle_id: UUID, *, actor: ActorRef) -> ReviewCycle:
        """Open the cycle for form collection; requires at least one assignment."""
        self.get_cycle(cycle_id)
        if not self.list_assignments(cycle_id):
            raise GrowthError("add at least one assignment before activating the cycle")
        return self._transition_cycle(
            cycle_id, target=ReviewCycleStatus.ACTIVE, actor=actor, action="growth.cycle_activated"
        )

    def advance_to_reviewing(self, cycle_id: UUID, *, actor: ActorRef) -> ReviewCycle:
        self.get_cycle(cycle_id)
        pending = [item for item in self.list_assignments(cycle_id) if not item.terminal]
        if pending:
            raise GrowthError(f"{len(pending)} assignments still pending; submit or skip first")
        return self._transition_cycle(
            cycle_id,
            target=ReviewCycleStatus.REVIEWING,
            actor=actor,
            action="growth.cycle_reviewing",
        )

    def close_cycle(self, cycle_id: UUID, *, actor: ActorRef) -> ReviewCycle:
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
            cycle_id,
            target=ReviewCycleStatus.COMPLETED,
            actor=actor,
            action="growth.cycle_completed",
        )

    def cancel_cycle(self, cycle_id: UUID, *, actor: ActorRef, reason: str) -> ReviewCycle:
        if not reason.strip():
            raise GrowthError("cancelling a cycle requires a reason")
        return self._transition_cycle(
            cycle_id,
            target=ReviewCycleStatus.CANCELLED,
            actor=actor,
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
        actor: ActorRef,
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
            actor=actor,
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
        actor: ActorRef,
        ratings: dict[str, float],
        comments: str = "",
    ) -> ReviewAssignment:
        """Submit a reviewer's form. Humans only; ratings validated against the scale."""
        actor.require_human("submit a review form", GrowthError)
        assignment = self.get_assignment(assignment_id)
        if not self._is_assigned_reviewer(assignment, actor):
            # Without this, anyone holding people:read could file a performance
            # review in another person's name. The record kept the real
            # reviewer's id and stamped `submitted_by` with whoever called it,
            # so the two disagreed and `submitted_ratings` fed the impostor's
            # numbers into the employee's summary.
            raise GrowthError(
                f"only the assigned reviewer may submit this form; it belongs to "
                f"{assignment.reviewer_id}"
            )
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
                "submitted_by": actor.actor_id,
                "submitted_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        self._store.save_assignment(updated)
        self._record(
            cycle,
            action="growth.assignment_submitted",
            actor=actor,
            payload={"assignment_id": str(updated.id), "dimensions": sorted(ratings)},
        )
        return updated

    def skip_assignment(
        self, assignment_id: UUID, *, actor: ActorRef, reason: str
    ) -> ReviewAssignment:
        """Skip a form (e.g., reviewer left). Human decision with a reason."""
        actor.require_human("skip a review form", GrowthError)
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
                "skipped_by": actor.actor_id,
                "skipped_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        self._store.save_assignment(updated)
        self._record(
            cycle,
            action="growth.assignment_skipped",
            actor=actor,
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
        actor: ActorRef,
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
                    "draft_by": actor.actor_id,
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
                draft_by=actor.actor_id,
                draft_created_at=utc_now(),
            )
            self._store.add_summary(summary)

        self._record(
            cycle,
            action="growth.summary_drafted",
            actor=actor,
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

    def finalize_summary(
        self, summary_id: UUID, *, actor: ActorRef, final_text: str
    ) -> ReviewSummary:
        """Human-only finalization. The final text is what gets shared."""
        actor.require_human("finalize a review summary", GrowthError)
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
                "finalized_by": actor.actor_id,
                "finalized_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        self._store.save_summary(updated)
        self._record(
            cycle,
            action="growth.summary_finalized",
            actor=actor,
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
                    actor=ActorRef.system("scheduler"),
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
                    actor=ActorRef.system("scheduler"),
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
        actor: ActorRef,
        description: str = "",
        metric: str | None = None,
        cycle_id: UUID | None = None,
        start_on: date | None = None,
        due_on: date | None = None,
    ) -> Goal:
        actor.require_human("create a goal", GrowthError)
        if cycle_id is not None:
            self.get_cycle(cycle_id)
        goal = Goal(
            created_by=actor.actor_id,
            employee_id=employee_id,
            title=title,
            description=description,
            metric=metric,
            cycle_id=cycle_id,
            start_on=start_on,
            due_on=due_on,
        )
        self._store.add_goal(goal)
        self._record(
            goal,
            action="growth.goal_created",
            actor=actor,
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

    def activate_goal(self, goal_id: UUID, *, actor: ActorRef) -> Goal:
        actor.require_human("activate a goal", GrowthError)
        goal = self.get_goal(goal_id)
        if goal.status is not GoalStatus.DRAFT:
            raise GrowthError(f"goal is {goal.status.value}; cannot activate")
        updated = goal.model_copy(update={"status": GoalStatus.ACTIVE, "updated_at": utc_now()})
        self._store.save_goal(updated)
        self._record(updated, action="growth.goal_activated", actor=actor, payload={})
        return updated

    def update_progress(
        self, goal_id: UUID, *, percent: float, actor: ActorRef, note: str = ""
    ) -> Goal:
        actor.require_human("update goal progress", GrowthError)
        goal = self.get_goal(goal_id)
        if not goal.open:
            raise GrowthError(f"goal is {goal.status.value}; cannot update progress")
        if not 0.0 <= percent <= 100.0:
            raise GrowthError("progress must be between 0 and 100")
        updates = [
            *goal.updates,
            GoalUpdate(progress_percent=percent, note=note, by=actor.actor_id),
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
            actor=actor,
            payload={"percent": percent},
        )
        return updated

    def complete_goal(self, goal_id: UUID, *, actor: ActorRef, note: str = "") -> Goal:
        actor.require_human("complete a goal", GrowthError)
        goal = self.get_goal(goal_id)
        if not goal.open:
            raise GrowthError(f"goal is {goal.status.value}; cannot complete")
        updates = [*goal.updates, GoalUpdate(progress_percent=100.0, note=note, by=actor.actor_id)]
        updated = goal.model_copy(
            update={
                "status": GoalStatus.COMPLETED,
                "progress_percent": 100.0,
                "updates": updates,
                "updated_at": utc_now(),
            }
        )
        self._store.save_goal(updated)
        self._record(updated, action="growth.goal_completed", actor=actor, payload={})
        return updated

    def cancel_goal(self, goal_id: UUID, *, actor: ActorRef, reason: str) -> Goal:
        actor.require_human("cancel a goal", GrowthError)
        if not reason.strip():
            raise GrowthError("cancelling a goal requires a reason")
        goal = self.get_goal(goal_id)
        if not goal.open:
            raise GrowthError(f"goal is {goal.status.value}; cannot cancel")
        updated = goal.model_copy(update={"status": GoalStatus.CANCELLED, "updated_at": utc_now()})
        self._store.save_goal(updated)
        self._record(
            updated, action="growth.goal_cancelled", actor=actor, payload={"reason": reason}
        )
        return updated

    def overdue_goals(self, *, as_of: date | None = None) -> list[Goal]:
        return [goal for goal in self._store.list_goals() if goal.is_overdue(as_of=as_of)]

    # --- internals -----------------------------------------------------------

    def _require_human(self, actor: str, action: str) -> str:
        return require_named_human(actor, action, GrowthError)

    def _is_assigned_reviewer(self, assignment: ReviewAssignment, actor: ActorRef) -> bool:
        """Whether ``actor`` may file this assignment's form.

        The reviewer is a person, so identity comes from the API key -- and that
        makes the check an equality, not a permission. An HR admin may still file
        it on someone's behalf, because an unreachable manager is a real
        situation and an unattributable review is worse than a late one; that path
        stays visible because ``submitted_by`` then differs from ``reviewer_id``.
        """
        if assignment.reviewer_id == actor.actor_id:
            return True
        return actor.role == "hr_admin"

    def _record(
        self,
        subject: ReviewCycle | ReviewSummary | Goal,
        *,
        action: str,
        actor: ActorRef,
        payload: dict[str, object],
    ) -> None:
        subject_type = {
            ReviewCycle: "review_cycle",
            ReviewSummary: "review_summary",
            Goal: "goal",
        }[type(subject)]
        self._audit.append(
            actor=actor.audit_actor(),
            action=action,
            subject_type=subject_type,
            subject_id=str(subject.id),
            payload=payload,
        )
