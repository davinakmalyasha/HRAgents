from datetime import date, timedelta
from uuid import uuid4

import pytest

from hr_agents.identity import ActorRef
from hr_agents.models import ApproverRole, TaskPriority, TaskSource, TaskStatus
from hr_agents.services import TaskEngine, TaskError
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import TaskStore


@pytest.fixture
def engine() -> TaskEngine:
    return TaskEngine(TaskStore(), audit=AuditChain())


def test_create_and_audit(engine: TaskEngine) -> None:
    task = engine.create(title="Collect KTP", actor=ActorRef.legacy("hr-admin"))

    assert task.status is TaskStatus.OPEN
    assert task.source.value == "manual"
    assert engine._audit.verify() == -1
    assert engine._audit.entries[-1].action == "task.created"


def test_a_non_human_task_is_labelled_from_its_actor_not_from_the_caller(
    engine: TaskEngine,
) -> None:
    """The source follows the actor, so the two cannot contradict each other.

    This used to be `create_agent_task(agent_name=...)`, and two callers were
    mislabelling themselves: starting an onboarding plan recorded an *agent* as
    the creator when a person had done it, and the contract-expiry sweep recorded
    an agent when a timer had done it. An auditor reading the chain saw an
    autonomous system filing work against a named employee, and a human's own
    action attributed to software.
    """
    agent = engine.create_on_behalf_of(
        title="Chase missing NPWP",
        actor=ActorRef.agent("onboarding_coordinator"),
    )
    assert agent.source is TaskSource.AGENT
    assert agent.created_by == "agent:onboarding_coordinator"
    assert engine._audit.entries[-1].actor.provenance.value == "agent_tool"

    sweep = engine.create_on_behalf_of(
        title="Contract expiring in 7 days",
        actor=ActorRef.system("contract-expiry"),
    )
    assert sweep.source is TaskSource.SYSTEM
    assert sweep.created_by == "system:contract-expiry"
    assert engine._audit.entries[-1].actor.provenance.value == "system_job"

    human = engine.create_on_behalf_of(
        title="Draft the offer letter",
        actor=ActorRef.legacy("Sinta"),
    )
    assert human.source is TaskSource.MANUAL
    assert human.created_by == "Sinta"


def test_complete_flow(engine: TaskEngine) -> None:
    task = engine.create(title="Prepare contract", actor=ActorRef.legacy("hr"))
    done = engine.complete(task.id, actor=ActorRef.legacy("hr-admin"))

    assert done.status is TaskStatus.DONE
    assert done.completed_by == "hr-admin"
    assert done.completed_at is not None


def test_complete_twice_rejected(engine: TaskEngine) -> None:
    task = engine.create(title="X", actor=ActorRef.legacy("hr"))
    engine.complete(task.id, actor=ActorRef.legacy("hr"))
    with pytest.raises(TaskError, match="cannot complete"):
        engine.complete(task.id, actor=ActorRef.legacy("hr"))


def test_start_and_block_transitions(engine: TaskEngine) -> None:
    task = engine.create(title="X", actor=ActorRef.legacy("hr"))
    started = engine.start(task.id, actor=ActorRef.legacy("hr"))
    assert started.status is TaskStatus.IN_PROGRESS

    blocked = engine.block(task.id, actor=ActorRef.legacy("hr"), reason="waiting for document")
    assert blocked.status is TaskStatus.BLOCKED
    assert "waiting for document" in blocked.description


def test_cancel_with_reason(engine: TaskEngine) -> None:
    task = engine.create(title="X", actor=ActorRef.legacy("hr"))
    cancelled = engine.cancel(task.id, actor=ActorRef.legacy("hr"), reason="no longer needed")
    assert cancelled.status is TaskStatus.CANCELLED
    assert "no longer needed" in cancelled.description


def test_unknown_task_raises(engine: TaskEngine) -> None:
    with pytest.raises(TaskError, match="unknown task"):
        engine.complete(uuid4(), actor=ActorRef.legacy("hr"))


# --- queues ------------------------------------------------------------------


def test_open_tasks_overdue_first_then_due_date(engine: TaskEngine) -> None:
    today = date.today()
    overdue = engine.create(
        title="overdue", actor=ActorRef.legacy("hr"), due_on=today - timedelta(days=3)
    )
    soon = engine.create(
        title="soon", actor=ActorRef.legacy("hr"), due_on=today + timedelta(days=1)
    )
    later = engine.create(
        title="later", actor=ActorRef.legacy("hr"), due_on=today + timedelta(days=30)
    )
    no_due = engine.create(title="no due", actor=ActorRef.legacy("hr"))

    ordered = engine.open_tasks()
    assert [task.id for task in ordered] == [overdue.id, soon.id, later.id, no_due.id]


def test_overdue_detection(engine: TaskEngine) -> None:
    today = date.today()
    engine.create(title="late", actor=ActorRef.legacy("hr"), due_on=today - timedelta(days=1))
    engine.create(title="today", actor=ActorRef.legacy("hr"), due_on=today)
    engine.create(title="future", actor=ActorRef.legacy("hr"), due_on=today + timedelta(days=5))

    overdue = engine.overdue()
    assert [task.title for task in overdue] == ["late"]


def test_for_role_filters(engine: TaskEngine) -> None:
    engine.create(
        title="hr task", actor=ActorRef.legacy("sys"), assignee_role=ApproverRole.HR_ADMIN
    )
    engine.create(
        title="manager task", actor=ActorRef.legacy("sys"), assignee_role=ApproverRole.MANAGER
    )

    assert [task.title for task in engine.for_role(ApproverRole.HR_ADMIN)] == ["hr task"]


def test_completed_tasks_leave_the_queue(engine: TaskEngine) -> None:
    task = engine.create(title="X", actor=ActorRef.legacy("hr"))
    engine.complete(task.id, actor=ActorRef.legacy("hr"))
    assert engine.open_tasks() == []


def test_priority_recorded(engine: TaskEngine) -> None:
    task = engine.create(title="X", actor=ActorRef.legacy("hr"), priority=TaskPriority.HIGH)
    assert task.priority is TaskPriority.HIGH
