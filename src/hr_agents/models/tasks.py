"""Task and reminder models — the shared work-tracking primitive.

Used by onboarding checklists, document chasing, contract expiry reminders,
review cycles, and offboarding steps. Agents may create tasks; humans complete
them (or confirm agent-completed ones).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models.approval import ApproverRole
from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})


class TaskSource(StrEnum):
    MANUAL = "manual"
    AGENT = "agent"
    SYSTEM = "system"  # e.g. contract-expiry watcher


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class TaskItem(StrictModel):
    """One unit of work assigned to a human role."""

    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)

    assignee_role: ApproverRole | None = None
    assignee_id: str | None = Field(default=None, max_length=200)

    due_on: date | None = None
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.OPEN
    source: TaskSource = TaskSource.MANUAL

    related_subject: str | None = Field(default=None, max_length=60)
    related_id: str | None = Field(default=None, max_length=200)

    created_by: str = Field(default="system", max_length=200)
    completed_by: str | None = Field(default=None, max_length=200)
    completed_at: UtcDateTime | None = None

    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)

    @property
    def is_open(self) -> bool:
        return self.status not in TERMINAL_STATUSES

    def is_overdue(self, *, as_of: date | None = None) -> bool:
        if not self.is_open or self.due_on is None:
            return False
        return self.due_on < (as_of or date.today())
