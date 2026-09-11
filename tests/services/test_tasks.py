from datetime import date, timedelta
from uuid import uuid4

import pytest

from hr_agents.models import ApproverRole, TaskPriority, TaskStatus
from hr_agents.services import TaskEngine, TaskError
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import TaskStore


@pytest.fixture
def engine() -> TaskEngine:
    return TaskEngine(TaskStore(), audit=AuditChain())


def test_create_and_audit(engine: TaskEngine) -> None:
    task = engine.create(title="Collect KTP", created_by="hr-admin")

    assert task.status is TaskStatus.OPEN
    assert task.source.value == "manual"
    assert engine._audit.verify() == -1
    assert engine._audit.entries[-1].action == "task.created"


def test_agent_created_task_is_labeled(engine: TaskEngine) -> None:
    task = engine.create_agent_task(title="Chase missing NPWP", agent_name="onboarding_coordinator")
    assert task.source.value == "agent"
    assert task.created_by == "agent:onboarding_coordinator"
    assert engine._audit.entries[-1].actor.actor_type.value == "agent"


def test_complete_flow(engine: TaskEngine) -> None:
    task = engine.create(title="Prepare contract", created_by="hr")
    done = engine.complete(task.id, by="hr-admin")

    assert done.status is TaskStatus.DONE
    assert done.completed_by == "hr-admin"
    assert done.completed_at is not None


def test_complete_twice_rejected(engine: TaskEngine) -> None:
    task = engine.create(title="X", created_by="hr")
    engine.complete(task.id, by="hr")
    with pytest.raises(TaskError, match="cannot complete"):
        engine.complete(task.id, by="hr")


def test_start_and_block_transitions(engine: TaskEngine) -> None:
    task = engine.create(title="X", created_by="hr")
    started = engine.start(task.id, by="hr")
    assert started.status is TaskStatus.IN_PROGRESS

    blocked = engine.block(task.id, by="hr", reason="waiting for document")
    assert blocked.status is TaskStatus.BLOCKED
    assert "waiting for document" in blocked.description


def test_cancel_with_reason(engine: TaskEngine) -> None:
    task = engine.create(title="X", created_by="hr")
    cancelled = engine.cancel(task.id, by="hr", reason="no longer needed")
    assert cancelled.status is TaskStatus.CANCELLED
    assert "no longer needed" in cancelled.description


def test_unknown_task_raises(engine: TaskEngine) -> None:
    with pytest.raises(TaskError, match="unknown task"):
        engine.complete(uuid4(), by="hr")


# --- queues ------------------------------------------------------------------


def test_open_tasks_overdue_first_then_due_date(engine: TaskEngine) -> None:
    today = date.today()
    overdue = engine.create(title="overdue", created_by="hr", due_on=today - timedelta(days=3))
    soon = engine.create(title="soon", created_by="hr", due_on=today + timedelta(days=1))
    later = engine.create(title="later", created_by="hr", due_on=today + timedelta(days=30))
    no_due = engine.create(title="no due", created_by="hr")

    ordered = engine.open_tasks()
    assert [task.id for task in ordered] == [overdue.id, soon.id, later.id, no_due.id]


def test_overdue_detection(engine: TaskEngine) -> None:
    today = date.today()
    engine.create(title="late", created_by="hr", due_on=today - timedelta(days=1))
    engine.create(title="today", created_by="hr", due_on=today)
    engine.create(title="future", created_by="hr", due_on=today + timedelta(days=5))

    overdue = engine.overdue()
    assert [task.title for task in overdue] == ["late"]


def test_for_role_filters(engine: TaskEngine) -> None:
    engine.create(title="hr task", created_by="sys", assignee_role=ApproverRole.HR_ADMIN)
    engine.create(title="manager task", created_by="sys", assignee_role=ApproverRole.MANAGER)

    assert [task.title for task in engine.for_role(ApproverRole.HR_ADMIN)] == ["hr task"]


def test_completed_tasks_leave_the_queue(engine: TaskEngine) -> None:
    task = engine.create(title="X", created_by="hr")
    engine.complete(task.id, by="hr")
    assert engine.open_tasks() == []


def test_priority_recorded(engine: TaskEngine) -> None:
    task = engine.create(title="X", created_by="hr", priority=TaskPriority.HIGH)
    assert task.priority is TaskPriority.HIGH
