"""Human approval for destructive tool calls (MCP phase 7.4, plan 1.3).

An agent may *ask* for a destructive tool. It may not run one. The gate turns
that request into an ordinary approval carrying a dry-run preview of exactly
what would happen, and executes the call at most once — only after a named human
approved the same arguments that were previewed.

Three properties matter and are enforced here rather than by convention:

1. **No agent path.** The registry refuses a destructive tool before the handler
   is touched, so bypassing the gate means not going through the registry.
2. **Same arguments, or nothing.** The approval stores an argument digest; a
   call whose arguments differ from the approved preview cannot execute.
3. **At most once.** The approval is marked consumed on execution, so a replay
   cannot fire the tool a second time.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from hr_agents.models import (
    ActorType,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    AuditActor,
    Urgency,
    payload_digest,
)
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.tools.registry import ToolDefinition

TOOL_APPROVAL_SUBJECT = ApprovalSubject.DATA_CHANGE


class DestructiveToolError(RuntimeError):
    """Raised when a destructive call is not, or no longer, executable."""

    def __init__(self, message: str, *, request_id: UUID | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


@dataclass(frozen=True)
class ApprovalTicket:
    """What the agent gets back from :meth:`DestructiveToolGate.request`."""

    request_id: UUID
    tool_name: str
    agent_name: str
    approver_role: ApproverRole
    status: ApprovalStatus
    arguments_hash: str
    preview: dict[str, Any]


class DestructiveToolGate:
    """Bridges the approval engine and the tool registry for destructive tools."""

    def __init__(
        self,
        approvals: ApprovalEngine,
        *,
        audit: AuditChain | None = None,
        urgency: Urgency = Urgency.HIGH,
    ) -> None:
        self._approvals = approvals
        self._audit = audit or approvals.audit
        self._urgency = urgency

    # --- requesting -----------------------------------------------------

    def request(
        self,
        definition: ToolDefinition,
        *,
        agent_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ApprovalTicket:
        """Ask a human to approve one destructive call, with a dry-run preview.

        Read-only: the handler is called with ``dry_run=True`` and nothing is
        stored outside the approval request itself.
        """
        if not definition.requires_approval():
            raise DestructiveToolError(
                f"tool {definition.name!r} is not destructive and needs no approval"
            )
        normalized = agent_name.strip().lower()
        payload_arguments = dict(arguments or {})
        digest = payload_digest(payload_arguments)
        preview = self._preview(definition, payload_arguments)

        existing = self._find_open(definition.name, normalized, digest)
        if existing is not None:
            return self._ticket(definition, normalized, digest, existing)

        request = self._approvals.create(
            subject=TOOL_APPROVAL_SUBJECT,
            subject_id=definition.name,
            title=f"Run destructive tool: {definition.name}",
            summary=definition.description,
            assignee_role=definition.approver_role,
            requested_by=normalized,
            requested_by_agent=True,
            urgency=self._urgency,
            payload={
                "tool": definition.name,
                "agent": normalized,
                "arguments": payload_arguments,
                "arguments_hash": digest,
                "preview": preview,
            },
        )
        self._record(
            action="tool.destructive_requested",
            request_id=request.id,
            tool_name=definition.name,
            agent_name=normalized,
            arguments_hash=digest,
        )
        return self._ticket(definition, normalized, digest, request)

    # --- executing ------------------------------------------------------

    def execute_approved(
        self,
        definition: ToolDefinition,
        *,
        agent_name: str,
        arguments: dict[str, Any] | None = None,
        request_id: UUID | None = None,
    ) -> Any:
        """Execute a destructive call once, after a human approved it.

        ``request_id`` may be omitted: the gate then looks for the approved
        request matching these exact arguments.
        """
        if not definition.requires_approval():
            raise DestructiveToolError(
                f"tool {definition.name!r} is not destructive and needs no approval"
            )
        normalized = agent_name.strip().lower()
        payload_arguments = dict(arguments or {})
        digest = payload_digest(payload_arguments)

        request = (
            self._approvals.find(request_id)
            if request_id is not None
            else self._find_approved(definition.name, normalized)
        )
        if request is None:
            raise DestructiveToolError(
                f"no approval matches tool {definition.name!r} for this agent",
                request_id=request_id,
            )
        stored = request.payload
        if (
            stored.get("tool") != definition.name
            or stored.get("arguments_hash") != digest
            or stored.get("agent") != normalized
        ):
            raise DestructiveToolError(
                f"approval {request.id} was granted for different arguments",
                request_id=request.id,
            )
        if request.status is not ApprovalStatus.APPROVED:
            raise DestructiveToolError(
                f"approval {request.id} is {request.status.value}; only an approved call runs",
                request_id=request.id,
            )
        if stored.get("executed_at") is not None:
            raise DestructiveToolError(
                f"approval {request.id} was already executed once",
                request_id=request.id,
            )

        result = definition.handler(**payload_arguments)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise DestructiveToolError(
                f"tool {definition.name!r} is async and must be gated from an async caller",
                request_id=request.id,
            )
        self._approvals.mark_executed(request.id, by=normalized)
        self._record(
            action="tool.destructive_executed",
            request_id=request.id,
            tool_name=definition.name,
            agent_name=normalized,
            arguments_hash=digest,
        )
        return result

    # --- internals ------------------------------------------------------

    def _preview(self, definition: ToolDefinition, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run the handler in dry-run mode so the human approves a real preview."""
        try:
            result = definition.handler(dry_run=True, **arguments)
        except TypeError as exc:
            raise DestructiveToolError(
                f"tool {definition.name!r} cannot be previewed (no dry-run support): {exc}"
            ) from exc
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise DestructiveToolError(
                f"tool {definition.name!r} is async and cannot be previewed synchronously"
            )
        return {"result": result}

    def _find_open(self, tool_name: str, agent_name: str, digest: str) -> Any | None:
        for request in self._approvals.list_all():
            if not self._matches(request, tool_name, agent_name, digest):
                continue
            if request.status in {
                ApprovalStatus.PENDING,
                ApprovalStatus.ESCALATED,
                ApprovalStatus.APPROVED,
            }:
                return request
        return None

    def _find_approved(self, tool_name: str, agent_name: str) -> Any | None:
        """The approved request for this tool and agent, or the latest one.

        Falling back to the latest match is deliberate: the caller then learns
        that the call is still pending or was rejected, instead of a bare
        "nothing found". The argument digest is compared separately, so a
        mismatched call is always refused.
        """
        matches = [
            request
            for request in self._approvals.list_all()
            if self._belongs_to(request, tool_name, agent_name)
        ]
        if not matches:
            return None
        approved = [request for request in matches if request.status is ApprovalStatus.APPROVED]
        if approved:
            return max(approved, key=lambda item: item.created_at)
        return max(matches, key=lambda item: item.created_at)

    @staticmethod
    def _belongs_to(request: Any, tool_name: str, agent_name: str) -> bool:
        return (
            request.payload.get("tool") == tool_name and request.payload.get("agent") == agent_name
        )

    @staticmethod
    def _matches(request: Any, tool_name: str, agent_name: str, digest: str) -> bool:
        return (
            DestructiveToolGate._belongs_to(request, tool_name, agent_name)
            and request.payload.get("arguments_hash") == digest
        )

    def _ticket(
        self,
        definition: ToolDefinition,
        agent_name: str,
        digest: str,
        request: Any,
    ) -> ApprovalTicket:
        return ApprovalTicket(
            request_id=request.id,
            tool_name=definition.name,
            agent_name=agent_name,
            approver_role=request.assignee_role,
            status=request.status,
            arguments_hash=digest,
            preview=dict(request.payload.get("preview") or {}),
        )

    def _record(
        self,
        *,
        action: str,
        request_id: UUID,
        tool_name: str,
        agent_name: str,
        arguments_hash: str,
    ) -> None:
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.AGENT, actor_id=agent_name),
            action=action,
            subject_type="tool_approval",
            subject_id=str(request_id),
            payload={
                "tool": tool_name,
                "approval_id": str(request_id),
                "agent": agent_name,
                # Never the raw arguments: the human reads them on the approval.
                "arguments_hash": arguments_hash,
            },
        )


__all__ = [
    "TOOL_APPROVAL_SUBJECT",
    "ApprovalTicket",
    "DestructiveToolError",
    "DestructiveToolGate",
]
