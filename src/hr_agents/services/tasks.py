"""Task engine — the shared work-tracking primitive.

Used by onboarding checklists, document chasing, contract reminders, review
cycles, and offboarding steps. Agents may create tasks (clearly labeled);
humans complete them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from hr_agents.models import (
    ActorType,
    ApproverRole,
    AuditActor,
    TaskItem,
    TaskPriority,
    TaskSource,
    TaskStatus,
    utc_now,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import TaskStore


class TaskError(RuntimeError):
    """Raised for invalid task operations."""


@dataclass
class TaskUpdate:
    task: TaskItem
    action: str


class TaskEngine:
    """Create, assign, complete, and monitor tasks."""

    def __init__(self, store: TaskStore, *, audit: AuditChain | None = None) -> None:
        self._store = store
        self._audit = audit or AuditChain()

    # --- creation -------------------------------------------------------

    def create(
        self,
        *,
        title: str,
        created_by: str,
        description: str = "",
        assignee_role: ApproverRole | None = None,
        assignee_id: str | None = None,
        due_on: date | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        source: TaskSource = TaskSource.MANUAL,
        related_subject: str | None = None,
        related_id: str | None = None,
    ) -> TaskItem:
        task = TaskItem(
            title=title,
            description=description,
            assignee_role=assignee_role,
            assignee_id=assignee_id,
            due_on=due_on,
            priority=priority,
            source=source,
            related_subject=related_subject,
            related_id=related_id,
            created_by=created_by,
        )
        self._store.add(task)
        self._record(task, action="task.created", actor_id=created_by)
        return task

    def create_agent_task(
        self,
        *,
        title: str,
        agent_name: str,
        description: str = "",
        assignee_role: ApproverRole | None = None,
        due_on: date | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        related_subject: str | None = None,
        related_id: str | None = None,
    ) -> TaskItem:
        """An agent-created task. Source is recorded so humans can tell them apart."""
        return self.create(
            title=title,
            description=description,
            created_by=f"agent:{agent_name}",
            assignee_role=assignee_role,
            due_on=due_on,
            priority=priority,
            source=TaskSource.AGENT,
            related_subject=related_subject,
            related_id=related_id,
        )

    # --- lifecycle ------------------------------------------------------

    def start(self, task_id: UUID, *, by: str) -> TaskItem:
        return self._transition(
            task_id, target=TaskStatus.IN_PROGRESS, by=by, action="task.started"
        )

    def block(self, task_id: UUID, *, by: str, reason: str = "") -> TaskItem:
        return self._transition(
            task_id, target=TaskStatus.BLOCKED, by=by, action="task.blocked", note=reason
        )

    def complete(self, task_id: UUID, *, by: str) -> TaskItem:
        task = self._require(task_id)
        if not task.is_open:
            raise TaskError(f"task {task_id} is {task.status.value}; cannot complete")
        updated = task.model_copy(
            update={
                "status": TaskStatus.DONE,
                "completed_by": by,
                "completed_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
        self._store.save(updated)
        self._record(updated, action="task.completed", actor_id=by)
        return updated

    def cancel(self, task_id: UUID, *, by: str, reason: str = "") -> TaskItem:
        task = self._require(task_id)
        if not task.is_open:
            raise TaskError(f"task {task_id} is {task.status.value}; cannot cancel")
        updated = task.model_copy(
            update={
                "status": TaskStatus.CANCELLED,
                "completed_by": by,
                "completed_at": utc_now(),
                "description": (task.description + f"\nCancelled: {reason}").strip(),
                "updated_at": utc_now(),
            }
        )
        self._store.save(updated)
        self._record(updated, action="task.cancelled", actor_id=by)
        return updated

    # --- queries --------------------------------------------------------

    def open_tasks(self) -> list[TaskItem]:
        """Open work, overdue first, then earliest due date."""
        tasks = [task for task in self._store.list_all() if task.is_open]

        def sort_key(task: TaskItem) -> tuple[int, date, object]:
            overdue_rank = 0 if task.is_overdue() else 1
            return (overdue_rank, task.due_on or date.max, task.created_at)

        return sorted(tasks, key=sort_key)

    def overdue(self, *, as_of: date | None = None) -> list[TaskItem]:
        return [task for task in self.open_tasks() if task.is_overdue(as_of=as_of)]

    def for_role(self, role: ApproverRole) -> list[TaskItem]:
        return [task for task in self.open_tasks() if task.assignee_role is role]

    def open_for_related(self, *, related_subject: str, related_id: str) -> list[TaskItem]:
        """Open tasks linked to one related object (used for reminder dedup)."""
        return [
            task
            for task in self._store.list_all()
            if task.is_open
            and task.related_subject == related_subject
            and task.related_id == related_id
        ]

    # --- internals ------------------------------------------------------

    def _transition(
        self,
        task_id: UUID,
        *,
        target: TaskStatus,
        by: str,
        action: str,
        note: str = "",
    ) -> TaskItem:
        task = self._require(task_id)
        if not task.is_open:
            raise TaskError(f"task {task_id} is {task.status.value}; cannot transition")
        description = task.description
        if note:
            description = (description + f"\n{note}").strip()
        updated = task.model_copy(
            update={"status": target, "description": description, "updated_at": utc_now()}
        )
        self._store.save(updated)
        self._record(updated, action=action, actor_id=by)
        return updated

    def _require(self, task_id: UUID) -> TaskItem:
        task = self._store.get(task_id)
        if task is None:
            raise TaskError(f"unknown task {task_id}")
        return task

    def _record(self, task: TaskItem, *, action: str, actor_id: str) -> None:
        if actor_id.startswith("agent:"):
            actor_type = ActorType.AGENT
        elif actor_id == "system":
            actor_type = ActorType.SYSTEM
        else:
            actor_type = ActorType.HUMAN
        self._audit.append(
            actor=AuditActor(actor_type=actor_type, actor_id=actor_id),
            action=action,
            subject_type="task",
            subject_id=str(task.id),
            payload={
                "title": task.title,
                "status": task.status.value,
                "source": task.source.value,
                "assignee_role": task.assignee_role.value if task.assignee_role else None,
                "related_subject": task.related_subject,
                "related_id": task.related_id,
            },
        )
