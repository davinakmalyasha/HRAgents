from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from hr_agents.identity import ActorProvenance, ActorRef
from hr_agents.models import (
    ActorType,
    ApproverRole,
    AssignmentStatus,
    Goal,
    GoalStatus,
    ReviewAssignment,
    ReviewCycle,
    ReviewCycleKind,
    ReviewCycleStatus,
    SummaryStatus,
    TaskSource,
)
from hr_agents.rbac import RoleId
from hr_agents.services import (
    ApprovalEngine,
    ApprovalStore,
    EmployeeStore,
    GrowthError,
    GrowthService,
    TaskEngine,
    TaskStore,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.employees import EmployeeService

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
def employees(audit: AuditChain, approvals: ApprovalEngine) -> EmployeeService:
    return EmployeeService(EmployeeStore(), audit=audit, approvals=approvals)


@pytest.fixture
def service(tasks: TaskEngine, audit: AuditChain, employees: EmployeeService) -> GrowthService:
    return GrowthService(tasks=tasks, audit=audit, employees=employees)


def make_cycle(service: GrowthService, **overrides: object) -> ReviewCycle:
    defaults: dict[str, object] = {
        "name": "2026 H1 Review",
        "period_start": TODAY - timedelta(days=180),
        "period_end": TODAY,
        "actor": hr_admin(),
        "kind": ReviewCycleKind.MID_YEAR,
        "submission_due_on": TODAY + timedelta(days=3),
    }
    defaults.update(overrides)
    return service.create_cycle(**defaults)  # type: ignore[arg-type]


def hr_admin(actor_id: str = "Rina") -> ActorRef:
    """An authenticated principal carrying the HR admin role.

    ``submit_assignment`` compares the caller against the assigned reviewer, so
    the HR admin exception keys on a role claim the auth layer could produce --
    not on an actor whose name happens to contain "admin".
    """
    return ActorRef(
        actor_id=actor_id,
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=ApproverRole.HR_ADMIN.value,
    )


def signed_in_employee(actor_id: str, employee_id: UUID, role: str) -> ActorRef:
    """A principal the operator bound to an employee record.

    Ownership checks read ``employee_id``, which only ``from_principal`` can set
    and only from a configured binding. A test that means "the person this goal
    belongs to" has to say so the way a deployment would, or it ends up
    asserting against an actor production cannot produce.
    """
    return ActorRef(
        actor_id=actor_id,
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=role,
        employee_id=employee_id,
    )


def as_employee(service: EmployeeService, name: str = "Sari Dewi") -> tuple[UUID, ActorRef]:
    """Create an employee and the plain employee principal bound to them.

    Deliberately *not* an admin role: ``people:write`` would let this actor
    administer every record, which is the opposite of what the ownership tests
    are checking.
    """
    employee = service.create(
        full_name=name, actor=hr_admin(), hire_date=TODAY - timedelta(days=400)
    )
    return employee.id, signed_in_employee(
        name.split()[0].lower(), employee.id, RoleId.EMPLOYEE.value
    )


def make_assignment(
    service: GrowthService, cycle_id: UUID, *, reviewer_id: str = "lead-1"
) -> ReviewAssignment:
    return service.add_assignment(
        cycle_id,
        employee_id=_EMPLOYEE,
        reviewer_id=reviewer_id,
        actor=hr_admin(),
    )


_EMPLOYEE = uuid4()


# --- cycles ------------------------------------------------------------------


def test_create_cycle_requires_human(service: GrowthService) -> None:
    with pytest.raises(GrowthError, match="named human"):
        make_cycle(service, actor=ActorRef.agent("feedback_writer"))

    cycle = make_cycle(service)
    assert cycle.status is ReviewCycleStatus.DRAFT
    assert cycle.created_by == "Rina"


def test_cycle_requires_valid_period_and_scale(service: GrowthService) -> None:
    with pytest.raises(ValueError, match="period_end"):
        make_cycle(service, period_start=TODAY, period_end=TODAY - timedelta(days=1))
    with pytest.raises(ValueError, match="rating_scale_max"):
        make_cycle(service, rating_scale_min=5.0, rating_scale_max=1.0)


def test_activate_requires_assignment(service: GrowthService) -> None:
    cycle = make_cycle(service)
    with pytest.raises(GrowthError, match="at least one assignment"):
        service.activate_cycle(cycle.id, actor=hr_admin())

    make_assignment(service, cycle.id)
    activated = service.activate_cycle(cycle.id, actor=hr_admin())
    assert activated.status is ReviewCycleStatus.ACTIVE


def test_duplicate_assignment_rejected(service: GrowthService) -> None:
    cycle = make_cycle(service)
    make_assignment(service, cycle.id, reviewer_id="lead-1")
    with pytest.raises(GrowthError, match="already has an assignment"):
        make_assignment(service, cycle.id, reviewer_id="lead-1")


def test_assignment_closed_after_reviewing(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, actor=hr_admin())
    service.submit_assignment(
        assignment.id, actor=ActorRef.legacy("lead-1"), ratings={"delivery": 4.0}
    )
    service.advance_to_reviewing(cycle.id, actor=hr_admin())

    with pytest.raises(GrowthError, match="assignments are closed"):
        make_assignment(service, cycle.id, reviewer_id="lead-2")


# --- submissions ---------------------------------------------------------------


def test_submission_validates_ratings_against_scale(service: GrowthService) -> None:
    cycle = make_cycle(service, rating_scale_min=1.0, rating_scale_max=5.0)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, actor=hr_admin())

    with pytest.raises(GrowthError, match=r"scale is 1\.0-5\.0"):
        service.submit_assignment(
            assignment.id, actor=ActorRef.legacy("lead-1"), ratings={"delivery": 6.0}
        )
    with pytest.raises(GrowthError, match="at least one rating"):
        service.submit_assignment(assignment.id, actor=ActorRef.legacy("lead-1"), ratings={})

    submitted = service.submit_assignment(
        assignment.id,
        actor=ActorRef.legacy("lead-1"),
        ratings={"delivery": 4.5, "collaboration": 4.0},
    )
    assert submitted.status is AssignmentStatus.SUBMITTED
    assert submitted.submitted_at is not None


def test_agents_cannot_submit(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, actor=hr_admin())

    with pytest.raises(GrowthError, match="named human"):
        service.submit_assignment(
            assignment.id, actor=ActorRef.agent("feedback_writer"), ratings={"delivery": 4.0}
        )


def test_only_the_assigned_reviewer_may_file_the_form(service: GrowthService) -> None:
    """A performance review is a statement about someone, by a named person.

    ``submit_assignment`` checked only that the caller was a human. Anyone who
    could read the cycle could therefore file the assigned reviewer's form, and
    the ratings they typed became the employee's performance summary. The record
    kept the real reviewer's id while ``submitted_by`` named the impostor, so the
    two disagreed on the face of the same row.
    """
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id, reviewer_id="lead-1")
    service.activate_cycle(cycle.id, actor=hr_admin())

    with pytest.raises(GrowthError, match="only the assigned reviewer"):
        service.submit_assignment(
            assignment.id, actor=ActorRef.legacy("colleague-9"), ratings={"delivery": 1.0}
        )

    unchanged = service.get_assignment(assignment.id)
    assert unchanged.status is AssignmentStatus.PENDING
    assert unchanged.submitted_by is None
    assert unchanged.ratings == {}


def test_an_hr_admin_may_file_a_reviewers_form_for_them(service: GrowthService) -> None:
    """The documented exception: an unreachable manager must not block a cycle.

    The check is an identity comparison, not a permission, so it needs a way to
    say "this is not the reviewer". HR admin is the one role allowed to, and the
    substitution stays visible because ``submitted_by`` then differs from
    ``reviewer_id``.
    """
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id, reviewer_id="lead-1")
    service.activate_cycle(cycle.id, actor=hr_admin())

    submitted = service.submit_assignment(
        assignment.id, actor=hr_admin("Rina"), ratings={"delivery": 3.0}
    )

    assert submitted.status is AssignmentStatus.SUBMITTED
    assert submitted.reviewer_id == "lead-1"
    assert submitted.submitted_by == "Rina"


def test_submission_requires_active_cycle(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    # cycle still DRAFT
    with pytest.raises(GrowthError, match="forms are closed"):
        service.submit_assignment(
            assignment.id, actor=ActorRef.legacy("lead-1"), ratings={"delivery": 4.0}
        )


def test_skip_requires_human_and_reason(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, actor=hr_admin())

    with pytest.raises(GrowthError, match="named human"):
        service.skip_assignment(assignment.id, actor=ActorRef.agent("x"), reason="left")
    with pytest.raises(GrowthError, match="requires a reason"):
        service.skip_assignment(assignment.id, actor=hr_admin(), reason=" ")

    skipped = service.skip_assignment(assignment.id, actor=hr_admin(), reason="reviewer left")
    assert skipped.status is AssignmentStatus.SKIPPED


def test_advance_to_reviewing_requires_no_pending(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, actor=hr_admin())

    with pytest.raises(GrowthError, match="assignments still pending"):
        service.advance_to_reviewing(cycle.id, actor=hr_admin())

    service.submit_assignment(
        assignment.id, actor=ActorRef.legacy("lead-1"), ratings={"delivery": 4.0}
    )
    advanced = service.advance_to_reviewing(cycle.id, actor=hr_admin())
    assert advanced.status is ReviewCycleStatus.REVIEWING


# --- summaries -------------------------------------------------------------------


def make_submitted_assignment(service: GrowthService) -> tuple[ReviewCycle, ReviewAssignment]:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, actor=hr_admin())
    service.submit_assignment(
        assignment.id,
        actor=ActorRef.legacy("lead-1"),
        ratings={"delivery": 4.5, "communication": 4.0},
    )
    return cycle, assignment


def test_draft_requires_submitted_forms(service: GrowthService) -> None:
    cycle = make_cycle(service)
    make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, actor=hr_admin())
    with pytest.raises(GrowthError, match="grounded in them"):
        service.draft_summary(
            cycle.id, _EMPLOYEE, draft_text="draft", actor=ActorRef.agent("feedback_writer")
        )


def test_agent_can_draft_summary(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    summary = service.draft_summary(
        cycle.id,
        _EMPLOYEE,
        draft_text="Strong delivery this period.",
        actor=ActorRef.agent("feedback_writer"),
    )
    assert summary.status is SummaryStatus.PENDING_REVIEW
    assert summary.agent_draft.startswith("Strong")
    assert summary.final_text is None
    assert summary.draft_by == "agent:feedback_writer"


def test_draft_can_be_refreshed_before_finalize(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    first = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="v1", actor=ActorRef.agent("feedback_writer")
    )
    second = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="v2", actor=ActorRef.agent("feedback_writer")
    )

    assert second.id == first.id
    assert second.agent_draft == "v2"
    assert len(service.list_summaries(cycle.id)) == 1


def test_finalize_is_human_only_and_terminal(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    summary = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="draft", actor=ActorRef.agent("feedback_writer")
    )

    with pytest.raises(GrowthError, match="named human"):
        service.finalize_summary(
            summary.id, actor=ActorRef.agent("feedback_writer"), final_text="x"
        )

    finalized = service.finalize_summary(
        summary.id, actor=hr_admin(), final_text="Final human-edited text."
    )
    assert finalized.status is SummaryStatus.FINALIZED
    assert finalized.finalized_by == "Rina"
    assert finalized.finalized_at is not None

    with pytest.raises(GrowthError, match="already finalized"):
        service.finalize_summary(summary.id, actor=hr_admin(), final_text="again")
    with pytest.raises(GrowthError, match="can no longer be re-drafted"):
        service.draft_summary(
            cycle.id, _EMPLOYEE, draft_text="new", actor=ActorRef.agent("feedback_writer")
        )


def test_close_cycle_requires_finalized_summaries(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    service.advance_to_reviewing(cycle.id, actor=hr_admin())
    summary = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="draft", actor=ActorRef.agent("feedback_writer")
    )

    with pytest.raises(GrowthError, match="await human finalization"):
        service.close_cycle(cycle.id, actor=hr_admin())

    service.finalize_summary(summary.id, actor=hr_admin(), final_text="done")
    closed = service.close_cycle(cycle.id, actor=hr_admin())
    assert closed.status is ReviewCycleStatus.COMPLETED


def test_cancel_cycle_requires_reason(service: GrowthService) -> None:
    cycle = make_cycle(service)
    make_assignment(service, cycle.id)
    with pytest.raises(GrowthError, match="requires a reason"):
        service.cancel_cycle(cycle.id, actor=hr_admin(), reason="")

    cancelled = service.cancel_cycle(cycle.id, actor=hr_admin(), reason="merged with H2")
    assert cancelled.status is ReviewCycleStatus.CANCELLED
    with pytest.raises(GrowthError, match="cannot move cycle"):
        service.activate_cycle(cycle.id, actor=hr_admin())


def test_submitted_ratings_collected_per_dimension(service: GrowthService) -> None:
    cycle = make_cycle(service)
    first = make_assignment(service, cycle.id, reviewer_id="lead-1")
    second = make_assignment(service, cycle.id, reviewer_id="lead-2")
    service.activate_cycle(cycle.id, actor=hr_admin())
    service.submit_assignment(first.id, actor=ActorRef.legacy("lead-1"), ratings={"delivery": 4.0})
    service.submit_assignment(second.id, actor=ActorRef.legacy("lead-2"), ratings={"delivery": 5.0})

    assert service.submitted_ratings(cycle.id, _EMPLOYEE) == {"delivery": [4.0, 5.0]}


# --- reminders --------------------------------------------------------------------


def test_reminders_create_tasks_and_deduplicate(service: GrowthService, tasks: TaskEngine) -> None:
    cycle = make_cycle(service, submission_due_on=TODAY + timedelta(days=1))
    assignment = make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, actor=hr_admin())

    first_run = service.run_reminders(actor=hr_admin("Rina"), as_of=TODAY)
    assert len(first_run) == 1
    assert first_run[0].kind == "assignment_due"
    assert first_run[0].subject_id == assignment.id
    created_task = tasks.open_for_related(
        related_subject="review_assignment", related_id=str(assignment.id)
    )
    assert len(created_task) == 1
    assert created_task[0].source is TaskSource.SYSTEM

    second_run = service.run_reminders(actor=hr_admin("Rina"), as_of=TODAY)
    assert second_run == []
    assert len(tasks.open_tasks()) == 1


def test_reminders_skip_far_future_assignments(service: GrowthService) -> None:
    cycle = make_cycle(service, submission_due_on=TODAY + timedelta(days=30))
    make_assignment(service, cycle.id)
    service.activate_cycle(cycle.id, actor=hr_admin())

    assert service.run_reminders(actor=hr_admin("Rina"), as_of=TODAY) == []


def test_reminders_cover_unfinalized_summaries(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    service.advance_to_reviewing(cycle.id, actor=hr_admin())
    summary = service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="draft", actor=ActorRef.agent("feedback_writer")
    )

    created = service.run_reminders(actor=hr_admin("Rina"), as_of=TODAY)

    assert [item.kind for item in created] == ["summary_awaiting_finalize"]
    assert created[0].subject_id == summary.id


def test_reminders_ignore_cancelled_cycles(service: GrowthService) -> None:
    cycle = make_cycle(service, submission_due_on=TODAY)
    make_assignment(service, cycle.id)
    service.cancel_cycle(cycle.id, actor=hr_admin(), reason="nope")

    assert service.run_reminders(actor=hr_admin("Rina"), as_of=TODAY) == []


# --- goals --------------------------------------------------------------------------


def test_goal_lifecycle(service: GrowthService) -> None:
    goal = service.create_goal(
        employee_id=_EMPLOYEE,
        title="Ship onboarding v2",
        actor=hr_admin(),
        metric="launch by Q3",
        due_on=TODAY + timedelta(days=60),
    )
    assert goal.status is GoalStatus.DRAFT

    with pytest.raises(GrowthError, match="named human"):
        service.activate_goal(goal.id, actor=ActorRef.agent("planner"))

    active = service.activate_goal(goal.id, actor=hr_admin())
    assert active.status is GoalStatus.ACTIVE

    updated = service.update_progress(goal.id, percent=40.0, actor=hr_admin(), note="beta done")
    assert updated.progress_percent == 40.0
    assert len(updated.updates) == 1
    assert updated.updates[0].by == "Rina"

    completed = service.complete_goal(goal.id, actor=hr_admin(), note="shipped")
    assert completed.status is GoalStatus.COMPLETED
    assert completed.progress_percent == 100.0
    assert len(completed.updates) == 2

    with pytest.raises(GrowthError, match="cannot update progress"):
        service.update_progress(goal.id, percent=50.0, actor=hr_admin())


def test_goal_progress_can_activate_draft(service: GrowthService) -> None:
    goal = service.create_goal(employee_id=_EMPLOYEE, title="X", actor=hr_admin())
    updated = service.update_progress(goal.id, percent=10.0, actor=hr_admin())
    assert updated.status is GoalStatus.ACTIVE


def test_goal_progress_bounds(service: GrowthService) -> None:
    goal = service.create_goal(employee_id=_EMPLOYEE, title="X", actor=hr_admin())
    with pytest.raises(GrowthError, match="between 0 and 100"):
        service.update_progress(goal.id, percent=101.0, actor=hr_admin())


def test_cancel_goal_requires_reason(service: GrowthService) -> None:
    goal = service.create_goal(employee_id=_EMPLOYEE, title="X", actor=hr_admin())
    with pytest.raises(GrowthError, match="requires a reason"):
        service.cancel_goal(goal.id, actor=hr_admin(), reason="")

    cancelled = service.cancel_goal(goal.id, actor=hr_admin(), reason="deprioritized")
    assert cancelled.status is GoalStatus.CANCELLED


def test_overdue_goals(service: GrowthService) -> None:
    overdue = service.create_goal(
        employee_id=_EMPLOYEE,
        title="Late goal",
        actor=hr_admin(),
        due_on=TODAY - timedelta(days=1),
    )
    service.create_goal(
        employee_id=_EMPLOYEE,
        title="Future goal",
        actor=hr_admin(),
        due_on=TODAY + timedelta(days=30),
    )

    assert [goal.id for goal in service.overdue_goals()] == [overdue.id]


def test_goal_cycle_link_validated(service: GrowthService) -> None:
    with pytest.raises(GrowthError, match="unknown review cycle"):
        service.create_goal(
            employee_id=_EMPLOYEE,
            title="X",
            actor=hr_admin(),
            cycle_id=uuid4(),
        )


def test_audit_chain_records_growth_actions(service: GrowthService) -> None:
    cycle, _ = make_submitted_assignment(service)
    service.draft_summary(
        cycle.id, _EMPLOYEE, draft_text="d", actor=ActorRef.agent("feedback_writer")
    )

    actions = [entry.action for entry in service._audit.entries]
    assert "growth.cycle_created" in actions
    assert "growth.assignment_created" in actions
    assert "growth.assignment_submitted" in actions
    assert "growth.summary_drafted" in actions


def test_reviewer_role_defaults_to_manager(service: GrowthService) -> None:
    cycle = make_cycle(service)
    assignment = make_assignment(service, cycle.id)
    assert assignment.reviewer_role is ApproverRole.MANAGER


# --- goal ownership ------------------------------------------------------------
#
# The four goal transitions each took any `goal_id` they were handed and only
# recorded who did it. That was safe while only people who could *create* goals
# could reach them, and it stops being safe the moment an employee can move their
# own goal along: "act on a goal" becomes an operation against someone else's
# record by naming their id.


def _goal_for(service: GrowthService, employee_id: UUID) -> Goal:
    return service.create_goal(
        employee_id=employee_id, title="Ship onboarding v2", actor=hr_admin()
    )


def test_the_goal_owner_can_move_their_own_goal(
    service: GrowthService, employees: EmployeeService
) -> None:
    employee_id, actor = as_employee(employees)
    goal = _goal_for(service, employee_id)

    active = service.activate_goal(goal.id, actor=actor)
    updated = service.update_progress(goal.id, percent=40.0, actor=actor, note="beta done")
    completed = service.complete_goal(goal.id, actor=actor, note="shipped")

    assert active.status is GoalStatus.ACTIVE
    assert updated.progress_percent == 40.0
    assert completed.status is GoalStatus.COMPLETED


def test_an_employee_cannot_move_somebody_elses_goal(
    service: GrowthService, employees: EmployeeService
) -> None:
    sari_id, _sari = as_employee(employees, "Sari Dewi")
    _budi_id, budi = as_employee(employees, "Budi Santoso")
    goal = _goal_for(service, sari_id)

    with pytest.raises(GrowthError, match="cannot update goal progress for employee"):
        service.update_progress(goal.id, percent=40.0, actor=budi)
    with pytest.raises(GrowthError, match="cannot cancel a goal for employee"):
        service.cancel_goal(goal.id, actor=budi, reason="not mine")
    with pytest.raises(GrowthError, match="cannot activate a goal for employee"):
        service.activate_goal(goal.id, actor=budi)

    unchanged = service.get_goal(goal.id)
    assert unchanged.status is GoalStatus.DRAFT
    assert unchanged.updates == []


def test_a_bare_string_actor_cannot_reach_a_goal(
    service: GrowthService, employees: EmployeeService
) -> None:
    """`ActorRef.legacy` owns nothing, so it reaches nothing.

    This is the case that decides whether the suite's old legacy actors keep
    working: they cannot, and they should not.
    """
    employee_id, _actor = as_employee(employees)
    goal = _goal_for(service, employee_id)

    with pytest.raises(GrowthError, match="cannot activate a goal for employee"):
        service.activate_goal(goal.id, actor=ActorRef.legacy("Rina"))


def test_an_unbound_principal_cannot_reach_a_goal(
    service: GrowthService, employees: EmployeeService
) -> None:
    """Authenticating is not the same as being somebody.

    A principal the operator never bound to an employee record has a role and an
    actor id, and is still nobody in the directory.
    """
    employee_id, _actor = as_employee(employees)
    goal = _goal_for(service, employee_id)
    unbound = ActorRef(
        actor_id="Nadia",
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.EMPLOYEE.value,
    )

    with pytest.raises(GrowthError, match="cannot update goal progress for employee"):
        service.update_progress(goal.id, percent=50.0, actor=unbound)


def test_a_people_administrator_can_move_any_goal(
    service: GrowthService, employees: EmployeeService
) -> None:
    employee_id, _actor = as_employee(employees)
    goal = _goal_for(service, employee_id)

    updated = service.update_progress(goal.id, percent=75.0, actor=hr_admin())

    assert updated.progress_percent == 75.0


def test_a_goals_manager_can_move_it(service: GrowthService, employees: EmployeeService) -> None:
    """The reporting line is what makes a manager's access to a goal possible.

    Without reading `Employee.manager_id`, a manager could neither progress a
    report's goal nor close one out, so the manager would have to be HR.
    """
    manager_id = employees.create(
        full_name="Budi Santoso", actor=hr_admin(), hire_date=TODAY - timedelta(days=900)
    ).id
    report_id = employees.create(
        full_name="Sari Dewi",
        actor=hr_admin(),
        hire_date=TODAY - timedelta(days=400),
        manager_id=manager_id,
    ).id
    manager_actor = ActorRef(
        actor_id="Budi",
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.MANAGER.value,
        employee_id=manager_id,
    )
    goal = _goal_for(service, report_id)

    updated = service.update_progress(goal.id, percent=60.0, actor=manager_actor)

    assert updated.progress_percent == 60.0


def test_a_goal_whose_owner_is_gone_is_not_broadened_by_that(
    service: GrowthService, employees: EmployeeService
) -> None:
    """An unknown owner has no manager, which narrows access rather than widening it.

    The reporting line is looked up in a directory that may not have the record
    any more. A missing lookup must fall back to "self or people:write", never to
    "allow", or a deleted employee would silently hand the goal to whoever asks.
    """
    orphan_id = uuid4()
    goal = _goal_for(service, orphan_id)
    _stranger_id, stranger = as_employee(employees, "Budi Santoso")

    with pytest.raises(GrowthError, match="cannot update goal progress for employee"):
        service.update_progress(goal.id, percent=30.0, actor=stranger)
