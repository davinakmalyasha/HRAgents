from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from hr_agents.models import (
    ApproverRole,
    AssignmentStatus,
    GoalStatus,
    ReviewAssignment,
    ReviewCycle,
    ReviewCycleKind,
    ReviewCycleStatus,
    SummaryStatus,
    TaskSource,
)
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    GrowthError,
    GrowthService,
    TaskEngine,
    TaskStore,
)
from hr_agents.services.audit import AuditChain

TODAY = date.today()


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def tasks(audit: AuditChain) -> TaskEngine:
    return TaskEngine(TaskStore(), audit=audit)


@pytest.fixture
def approvals(audit: AuditChain) -> ApprovalEngine:
    return ApprovalEngine(ApprovalStore(), audit=audit)


@pytest.fixture
def service(tasks: TaskEngine, audit: AuditChain) -> GrowthService:
    return GrowthService(tasks=tasks, audit=audit)


def make_cycle(service: GrowthService, **overrides: object) -> ReviewCycle:
    defaults: dict[str, object] = {
        "name": "2026 H1 Review",
        "period_start": TODAY - timedelta(days=180),
        "period_end": TODAY,
        "created_by": "hr-admin",
        "kind": ReviewCycleKind.MID_YEAR,
        "submission_due_on": TODAY + timedelta(days=3),
    }
    defaults.update(overrides)
    return service.create_cycle(**defaults)  # type: ignore[arg-type]


def make_assignment(
    service: GrowthService, cycle_id: UUID, *, reviewer_id: str = "lead-1"
) -> ReviewAssignment:
    return service.add_assignment(
        cycle_id,
        employee_id=_EMPLOYEE,
        reviewer_id=reviewer_id,
        created_by="hr-admin",
    )


_EMPLOYEE = uuid4()


# --- cycles ------------------------------------------------------------------


def test_create_cycle_requires_human(service: GrowthService) -> None:
    with pytest.raises(GrowthError, match="named human"):
        make_cycle(service, created_by="agent:feedback_writer")

    cycle = make_cycle(service)
    assert cycle.status is ReviewCycleStatus.DRAFT
    assert cycle.created_by == "hr-admin"


def test_cycle_requires_valid_period_and_scale(service: GrowthService) -> None:
    with pytest.raises(ValueError, match="period_end"):
        make_cycle(service, period_start=TODAY, period_end=TODAY - timedelta(days=1))
    with pytest.raises(ValueError, match="rating_scale_max"):
        make_cycle(service, rating_scale_min=5.0, rating_scale_max=1.0)


def test_activate_requires_assignment(service: GrowthService) -> None:
    cycle = make_cycle(service)
    with pytest.raises(GrowthError, match="at least one assignment"):
        service.activate_cycle(cycle.id, by="hr-admin")

    make_assignment(service, cycle.id)
    activated = service.activate_cycle(cycle.id, by="hr-admin")
    assert activated.status is ReviewCycleStatus.ACTIVE


def test_duplicate_assignment_rejected(service: GrowthService) -> None:
    cycle = make_cycle(service)
    make_assignment(service, cycle.id, reviewer_id="lead-1")
    with pytest.raises(GrowthError, match="already has an assignment"):
        make_assignment(service, cycle.id, reviewer_id="lead-1")


def test_assignment_closed_after_reviewing(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, by="hr-admin")
    service.submit_assignment(assignment.id, by="lead-1", ratings={"delivery": 4.0})
    service.advance_to_reviewing(cycle.id, by="hr-admin")

    with pytest.raises(GrowthError, match="assignments are closed"):
        make_assignment(service, cycle.id, reviewer_id="lead-2")


# --- submissions ---------------------------------------------------------------


def test_submission_validates_ratings_against_scale(service: GrowthService) -> None:
    cycle = make_cycle(service, rating_scale_min=1.0, rating_scale_max=5.0)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, by="hr-admin")

    with pytest.raises(GrowthError, match=r"scale is 1\.0-5\.0"):
        service.submit_assignment(assignment.id, by="lead-1", ratings={"delivery": 6.0})
    with pytest.raises(GrowthError, match="at least one rating"):
        service.submit_assignment(assignment.id, by="lead-1", ratings={})

    submitted = service.submit_assignment(
        assignment.id, by="lead-1", ratings={"delivery": 4.5, "collaboration": 4.0}
    )
    assert submitted.status is AssignmentStatus.SUBMITTED
    assert submitted.submitted_at is not None


def test_agents_cannot_submit(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, by="hr-admin")

    with pytest.raises(GrowthError, match="named human"):
        service.submit_assignment(
            assignment.id, by="agent:feedback_writer", ratings={"delivery": 4.0}
        )


def test_submission_requires_active_cycle(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    # cycle still DRAFT
    with pytest.raises(GrowthError, match="forms are closed"):
        service.submit_assignment(assignment.id, by="lead-1", ratings={"delivery": 4.0})


def test_skip_requires_human_and_reason(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, by="hr-admin")

    with pytest.raises(GrowthError, match="named human"):
        service.skip_assignment(assignment.id, by="agent:x", reason="left")
    with pytest.raises(GrowthError, match="requires a reason"):
        service.skip_assignment(assignment.id, by="hr-admin", reason=" ")

    skipped = service.skip_assignment(assignment.id, by="hr-admin", reason="reviewer left")
    assert skipped.status is AssignmentStatus.SKIPPED


def test_advance_to_reviewing_requires_no_pending(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, by="hr-admin")

    with pytest.raises(GrowthError, match="assignments still pending"):
        service.advance_to_reviewing(cycle.id, by="hr-admin")

    service.submit_assignment(assignment.id, by="lead-1", ratings={"delivery": 4.0})
    advanced = service.advance_to_reviewing(cycle.id, by="hr-admin")
    assert advanced.status is ReviewCycleStatus.REVIEWING


# --- summaries -------------------------------------------------------------------


def make_submitted_assignment(service: GrowthService) -> tuple[ReviewCycle, ReviewAssignment]:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, by="hr-admin")
    service.submit_assignment(
        assignment.id, by="lead-1", ratings={"delivery": 4.5, "communication": 4.0}
    )
    return cycle, assignment


def test_draft_requires_submitted_forms(service: GrowthService) -> None:
    cycle = make_cycle(service)
    make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, by="hr-admin")
    with pytest.raises(GrowthError, match="grounded in them"):
        service.draft_summary(
            cycle.id, _EMPLOYEE, draft_text="draft", drafted_by="agent:feedback_writer"
        )


def test_agent_can_draft_summary(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    summary = service.draft_summary(
        cycle.id,
        _EMPLOYEE,
        draft_text="Strong delivery this period.",
        drafted_by="agent:feedback_writer",
    )
    assert summary.status is SummaryStatus.PENDING_REVIEW
    assert summary.agent_draft.startswith("Strong")
    assert summary.final_text is None
    assert summary.draft_by == "agent:feedback_writer"


def test_draft_can_be_refreshed_before_finalize(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    first = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="v1", drafted_by="agent:feedback_writer"
    )
    second = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="v2", drafted_by="agent:feedback_writer"
    )

    assert second.id == first.id
    assert second.agent_draft == "v2"
    assert len(service.list_summaries(cycle.id)) == 1


def test_finalize_is_human_only_and_terminal(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    summary = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="draft", drafted_by="agent:feedback_writer"
    )

    with pytest.raises(GrowthError, match="named human"):
        service.finalize_summary(summary.id, by="agent:feedback_writer", final_text="x")

    finalized = service.finalize_summary(
        summary.id, by="hr-admin", final_text="Final human-edited text."
    )
    assert finalized.status is SummaryStatus.FINALIZED
    assert finalized.finalized_by == "hr-admin"
    assert finalized.finalized_at is not None

    with pytest.raises(GrowthError, match="already finalized"):
        service.finalize_summary(summary.id, by="hr-admin", final_text="again")
    with pytest.raises(GrowthError, match="can no longer be re-drafted"):
        service.draft_summary(
            cycle.id, _EMPLOYEE, draft_text="new", drafted_by="agent:feedback_writer"
        )


def test_close_cycle_requires_finalized_summaries(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    service.advance_to_reviewing(cycle.id, by="hr-admin")
    summary = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="draft", drafted_by="agent:feedback_writer"
    )

    with pytest.raises(GrowthError, match="await human finalization"):
        service.close_cycle(cycle.id, by="hr-admin")

    service.finalize_summary(summary.id, by="hr-admin", final_text="done")
    closed = service.close_cycle(cycle.id, by="hr-admin")
    assert closed.status is ReviewCycleStatus.COMPLETED


def test_cancel_cycle_requires_reason(service: GrowthService) -> None:
    cycle = make_cycle(service)
    make_assignment(service, cycle.id)
    with pytest.raises(GrowthError, match="requires a reason"):
        service.cancel_cycle(cycle.id, by="hr-admin", reason="")

    cancelled = service.cancel_cycle(cycle.id, by="hr-admin", reason="merged with H2")
    assert cancelled.status is ReviewCycleStatus.CANCELLED
    with pytest.raises(GrowthError, match="cannot move cycle"):
        service.activate_cycle(cycle.id, by="hr-admin")


def test_submitted_ratings_collected_per_dimension(service: GrowthService) -> None:
    cycle = make_cycle(service)
    first = make_assignment(service, cycle.id, reviewer_id="lead-1")
    second = make_assignment(service, cycle.id, reviewer_id="lead-2")
    service.activate_cycle(cycle.id, by="hr-admin")
    service.submit_assignment(first.id, by="lead-1", ratings={"delivery": 4.0})
    service.submit_assignment(second.id, by="lead-2", ratings={"delivery": 5.0})

    assert service.submitted_ratings(cycle.id, _EMPLOYEE) == {"delivery": [4.0, 5.0]}


# --- reminders --------------------------------------------------------------------


def test_reminders_create_tasks_and_deduplicate(service: GrowthService, tasks: TaskEngine) -> None:
    cycle = make_cycle(service, submission_due_on=TODAY + timedelta(days=1))
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, by="hr-admin")

    first_run = service.run_reminders(as_of=TODAY)
    assert len(first_run) == 1
    assert first_run[0].kind == "assignment_due"
    assert first_run[0].subject_id == assignment.id
    created_task = tasks.open_for_related(
        related_subject="review_assignment", related_id=str(assignment.id)
    )
    assert len(created_task) == 1
    assert created_task[0].source is TaskSource.SYSTEM

    second_run = service.run_reminders(as_of=TODAY)
    assert second_run == []
    assert len(tasks.open_tasks()) == 1


def test_reminders_skip_far_future_assignments(service: GrowthService) -> None:
    cycle = make_cycle(service, submission_due_on=TODAY + timedelta(days=30))
    make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, by="hr-admin")

    assert service.run_reminders(as_of=TODAY) == []


def test_reminders_cover_unfinalized_summaries(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    service.advance_to_reviewing(cycle.id, by="hr-admin")
    summary = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="draft", drafted_by="agent:feedback_writer"
    )

    created = service.run_reminders(as_of=TODAY)

    assert [item.kind for item in created] == ["summary_awaiting_finalize"]
    assert created[0].subject_id == summary.id


def test_reminders_ignore_cancelled_cycles(service: GrowthService) -> None:
    cycle = make_cycle(service, submission_due_on=TODAY)
    make_assignment(service, cycle.id)
    service.cancel_cycle(cycle.id, by="hr-admin", reason="nope")

    assert service.run_reminders(as_of=TODAY) == []


# --- goals --------------------------------------------------------------------------


def test_goal_lifecycle(service: GrowthService) -> None:
    goal = service.create_goal(
        employee_id=_EMPLOYEE,
        title="Ship onboarding v2",
        created_by="hr-admin",
        metric="launch by Q3",
        due_on=TODAY + timedelta(days=60),
    )
    assert goal.status is GoalStatus.DRAFT

    with pytest.raises(GrowthError, match="named human"):
        service.activate_goal(goal.id, by="agent:planner")

    active = service.activate_goal(goal.id, by="hr-admin")
    assert active.status is GoalStatus.ACTIVE

    updated = service.update_progress(goal.id, percent=40.0, by="hr-admin", note="beta done")
    assert updated.progress_percent == 40.0
    assert len(updated.updates) == 1
    assert updated.updates[0].by == "hr-admin"

    completed = service.complete_goal(goal.id, by="hr-admin", note="shipped")
    assert completed.status is GoalStatus.COMPLETED
    assert completed.progress_percent == 100.0
    assert len(completed.updates) == 2

    with pytest.raises(GrowthError, match="cannot update progress"):
        service.update_progress(goal.id, percent=50.0, by="hr-admin")


def test_goal_progress_can_activate_draft(service: GrowthService) -> None:
    goal = service.create_goal(employee_id=_EMPLOYEE, title="X", created_by="hr-admin")
    updated = service.update_progress(goal.id, percent=10.0, by="hr-admin")
    assert updated.status is GoalStatus.ACTIVE


def test_goal_progress_bounds(service: GrowthService) -> None:
    goal = service.create_goal(employee_id=_EMPLOYEE, title="X", created_by="hr-admin")
    with pytest.raises(GrowthError, match="between 0 and 100"):
        service.update_progress(goal.id, percent=101.0, by="hr-admin")


def test_cancel_goal_requires_reason(service: GrowthService) -> None:
    goal = service.create_goal(employee_id=_EMPLOYEE, title="X", created_by="hr-admin")
    with pytest.raises(GrowthError, match="requires a reason"):
        service.cancel_goal(goal.id, by="hr-admin", reason="")

    cancelled = service.cancel_goal(goal.id, by="hr-admin", reason="deprioritized")
    assert cancelled.status is GoalStatus.CANCELLED


def test_overdue_goals(service: GrowthService) -> None:
    overdue = service.create_goal(
        employee_id=_EMPLOYEE,
        title="Late goal",
        created_by="hr-admin",
        due_on=TODAY - timedelta(days=1),
    )
    service.create_goal(
        employee_id=_EMPLOYEE,
        title="Future goal",
        created_by="hr-admin",
        due_on=TODAY + timedelta(days=30),
    )

    assert [goal.id for goal in service.overdue_goals()] == [overdue.id]


def test_goal_cycle_link_validated(service: GrowthService) -> None:
    with pytest.raises(GrowthError, match="unknown review cycle"):
        service.create_goal(
            employee_id=_EMPLOYEE,
            title="X",
            created_by="hr-admin",
            cycle_id=uuid4(),
        )


def test_audit_chain_records_growth_actions(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    service.draft_summary(cycle.id, _EMPLOYEE, draft_text="d", drafted_by="agent:feedback_writer")

    actions = [entry.action for entry in service._audit.entries]
    assert "growth.cycle_created" in actions
    assert "growth.assignment_created" in actions
    assert "growth.assignment_submitted" in actions
    assert "growth.summary_drafted" in actions


def test_reviewer_role_defaults_to_manager(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    assert assignment.reviewer_role is ApproverRole.MANAGER
