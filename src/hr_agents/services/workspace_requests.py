"""Cross-workspace request handoff: deterministic queue notes, human-invoked.

A handoff is a *request*, never an execution: the front door suggests target
workspaces, a human confirms, and the item lands in the target workspace's queue
for that team to pick up. Agents cannot create, claim, or complete handoffs —
the same rule that keeps every consequential action behind a named human.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models import ActorType, AuditActor, StrictModel, UtcDateTime, utc_now
from hr_agents.rbac import Principal
from hr_agents.services.audit import AuditChain
from hr_agents.workspaces import WorkspaceId, WorkspaceRegistry


class RequestStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    CLOSED = "closed"


class HandoffError(RuntimeError):
    """Raised for invalid handoff requests."""


class WorkspaceRequest(StrictModel):
    """One cross-workspace request: a queue item, never a decision."""

    id: UUID = Field(default_factory=uuid4)
    source_workspace: WorkspaceId
    target_workspace: WorkspaceId
    text: str = Field(min_length=1, max_length=8000)
    status: RequestStatus = RequestStatus.OPEN
    requested_by: str = Field(min_length=1, max_length=200)
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)


class WorkspaceRequestStore:
    """In-memory queue behind persistence primitives (Postgres adapter later)."""

    def __init__(self) -> None:
        self._items: dict[UUID, WorkspaceRequest] = {}

    def _load(self, request_id: UUID) -> WorkspaceRequest | None:
        return self._items.get(request_id)

    def _persist(self, record: WorkspaceRequest) -> None:
        self._items[record.id] = record

    def _iter(self) -> Iterator[WorkspaceRequest]:
        return iter(self._items.values())

    def get(self, request_id: UUID) -> WorkspaceRequest | None:
        return self._load(request_id)

    def list_all(self) -> list[WorkspaceRequest]:
        return sorted(self._iter(), key=lambda item: item.created_at)


class HandoffService:
    """Creates and reads cross-workspace requests; never executes work."""

    def __init__(
        self,
        *,
        registry: WorkspaceRegistry,
        audit: AuditChain,
        store: WorkspaceRequestStore | None = None,
    ) -> None:
        self._registry = registry
        self._audit = audit
        self._store = store or WorkspaceRequestStore()

    def request(
        self,
        *,
        message: str,
        principal: Principal,
        source_workspace: WorkspaceId,
        target_workspace: WorkspaceId,
    ) -> WorkspaceRequest:
        """Queue one request in another workspace. Blank or self-targets are rejected."""
        self._registry.get(source_workspace)
        self._registry.get(target_workspace)
        if source_workspace is target_workspace:
            raise HandoffError("a handoff must target a different workspace")
        text = message.strip()
        if not text:
            raise HandoffError("handoff message must not be blank")

        record = WorkspaceRequest(
            source_workspace=source_workspace,
            target_workspace=target_workspace,
            text=text,
            requested_by=principal.actor_id,
        )
        self._store._persist(record)
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=principal.actor_id),
            action="handoff.requested",
            subject_type="workspace_request",
            subject_id=str(record.id),
            payload={
                "source": source_workspace.value,
                "target": target_workspace.value,
                "characters": len(text),
            },
        )
        return record

    def open_for(self, workspace: WorkspaceId | None = None) -> list[WorkspaceRequest]:
        """Open requests, oldest first; filtered to one workspace when given."""
        if workspace is not None:
            self._registry.get(workspace)
        return [
            item
            for item in self._store.list_all()
            if item.status is RequestStatus.OPEN
            and (workspace is None or item.target_workspace is workspace)
        ]
