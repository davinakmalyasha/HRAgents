"""Tool registry: least-privilege, audited, dry-run-safe tool execution.

Every tool declares which agents may call it. There is no implicit "all agents"
access — an agent can only see and execute tools it was explicitly granted.
Every execution is recorded on the audit chain with an argument hash (never raw
arguments), so tool use is reconstructible without leaking candidate data.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from hr_agents.models import ActorType, ApproverRole, AuditActor, AuditEntry, payload_digest

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters for typing
    from hr_agents.tools.gating import DestructiveToolGate

ToolHandler = Callable[..., Any] | Callable[..., Awaitable[Any]]


class ToolNotFoundError(KeyError):
    """Raised when a tool name is unknown to the registry."""


class ToolPermissionError(PermissionError):
    """Raised when an agent attempts to use a tool it was not granted."""


class ToolApprovalRequired(RuntimeError):
    """Raised when an agent tries to run a destructive tool directly.

    The registry refuses before the handler is touched. A human-approved call
    goes through the approval gate instead, which executes exactly once.
    """


class AuditSink(Protocol):
    """Minimal contract for audit sinks (AuditChain, DB-backed chains, ...)."""

    def append(
        self,
        *,
        actor: AuditActor,
        action: str,
        subject_type: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
    ) -> AuditEntry: ...


class ToolImpact(StrEnum):
    """How much damage a tool can do, decided by the operator, not the agent.

    ``READ`` observes, ``WRITE`` changes state inside HRAgents, and
    ``DESTRUCTIVE`` changes something outside the system of record (an external
    MCP server, a payroll run, an erasure) and therefore never runs without a
    named human decision.
    """

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolDefinition:
    """A governed tool: metadata, permission scope, and the handler."""

    name: str
    description: str
    allowed_agents: frozenset[str]
    handler: ToolHandler
    dry_run_safe: bool = True
    tags: frozenset[str] = field(default_factory=frozenset)
    impact: ToolImpact = ToolImpact.READ
    approver_role: ApproverRole = ApproverRole.MANAGER

    def permits(self, agent_name: str) -> bool:
        return agent_name.strip().lower() in self.allowed_agents

    def requires_approval(self) -> bool:
        """Destructive tools are blocked until a human approves this exact call."""
        return self.impact is ToolImpact.DESTRUCTIVE

    def callable(self) -> ToolHandler:
        """The bare handler (for registration with an agent framework)."""
        return self.handler


class ToolRegistry:
    """Registry plus execution wrapper enforcing permissions and auditing.

    A registry can be narrowed to a least-privilege *view* with :meth:`scoped`
    (workspace packs use this): the view shares definitions and the audit sink
    with its parent, hides out-of-scope tools, and records denied attempts.
    """

    def __init__(
        self,
        audit: AuditSink | None = None,
        *,
        scope: Iterable[str] | None = None,
        scope_id: str | None = None,
        approval_gate: DestructiveToolGate | None = None,
    ) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._audit = audit
        self._scope: frozenset[str] | None = frozenset(scope) if scope is not None else None
        self._scope_id = scope_id
        self._approval_gate = approval_gate

    @property
    def approval_gate(self) -> DestructiveToolGate | None:
        return self._approval_gate

    def with_approval_gate(self, gate: DestructiveToolGate) -> ToolRegistry:
        """A registry that routes destructive tools through ``gate``.

        The parent view and its definitions are shared; only the gate is added.
        """
        gated = ToolRegistry(
            self._audit,
            scope=self._scope,
            scope_id=self._scope_id,
            approval_gate=gate,
        )
        gated._tools = self._tools
        return gated

    def scoped(self, tools: Iterable[str], *, scope_id: str | None = None) -> ToolRegistry:
        """A view limited to ``tools``, sharing definitions and the audit sink.

        Scoping an already-scoped view can only narrow it further, never widen.
        The approval gate travels with the view: narrowing scope must never be a
        way to drop the human gate on a destructive tool.
        """
        narrowed = frozenset(tools)
        if self._scope is not None:
            narrowed &= self._scope
        view = ToolRegistry(
            self._audit,
            scope=narrowed,
            scope_id=scope_id or self._scope_id,
            approval_gate=self._approval_gate,
        )
        view._tools = self._tools
        return view

    def register(self, definition: ToolDefinition) -> None:
        if self._scope is not None:
            raise ValueError("cannot register tools into a scoped view")
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool name: {definition.name!r}")
        if not definition.allowed_agents:
            raise ValueError(f"tool {definition.name!r} must declare allowed agents")
        if definition.requires_approval() and not definition.dry_run_safe:
            raise ValueError(
                f"destructive tool {definition.name!r} must be dry-run safe: "
                "the approval carries a preview of what would happen"
            )
        self._tools[definition.name] = definition

    def _visible(self, name: str) -> bool:
        if name not in self._tools:
            return False
        return self._scope is None or name in self._scope

    def get(self, name: str) -> ToolDefinition:
        if not self._visible(name):
            raise ToolNotFoundError(f"unknown tool: {name!r}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(name for name in self._tools if self._visible(name))

    def definitions_for(self, agent_name: str) -> list[ToolDefinition]:
        """Tools the agent is permitted to use in this view, sorted by name."""
        normalized = agent_name.strip().lower()
        return [
            tool
            for name, tool in sorted(self._tools.items())
            if self._visible(name) and tool.permits(normalized)
        ]

    def names_for(self, agent_name: str) -> list[str]:
        return [tool.name for tool in self.definitions_for(agent_name)]

    async def execute(
        self,
        *,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a tool as ``agent_name``, enforcing scope and auditing the call."""
        normalized = agent_name.strip().lower()
        if tool_name not in self._tools:
            raise ToolNotFoundError(f"unknown tool: {tool_name!r}")
        if self._scope is not None and tool_name not in self._scope:
            self._record(
                agent_name=normalized,
                tool_name=tool_name,
                arguments=arguments or {},
                outcome="denied",
                reason="workspace_scope",
            )
            raise ToolPermissionError(
                f"tool {tool_name!r} is outside workspace scope {self._scope_id!r}"
            )
        definition = self._tools[tool_name]
        if not definition.permits(normalized):
            self._record(
                agent_name=normalized,
                tool_name=tool_name,
                arguments=arguments or {},
                outcome="denied",
                reason="agent_scope",
            )
            raise ToolPermissionError(
                f"agent {normalized!r} is not permitted to use tool {tool_name!r}"
            )
        if definition.requires_approval():
            # Refused before the handler is touched: a destructive tool has no
            # direct execution path for an agent, only a human-approved one.
            self._record(
                agent_name=normalized,
                tool_name=tool_name,
                arguments=arguments or {},
                outcome="denied",
                reason="human_approval_required",
            )
            if self._approval_gate is None:
                raise ToolApprovalRequired(
                    f"tool {tool_name!r} is destructive and has no approval gate configured"
                )
            raise ToolApprovalRequired(
                f"tool {tool_name!r} is destructive: request approval, "
                "then execute the approved call"
            )

        outcome = "ok"
        try:
            result = definition.handler(**(arguments or {}))
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception:
            outcome = "error"
            raise
        finally:
            self._record(
                agent_name=normalized,
                tool_name=tool_name,
                arguments=arguments or {},
                outcome=outcome,
            )

    def _record(
        self,
        *,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        outcome: str,
        reason: str | None = None,
    ) -> None:
        if self._audit is None:
            return
        payload: dict[str, Any] = {
            "tool": tool_name,
            "arguments_hash": payload_digest(arguments),
            "outcome": outcome,
        }
        if self._scope_id is not None:
            payload["workspace"] = self._scope_id
        if reason is not None:
            payload["reason"] = reason
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.AGENT, actor_id=agent_name),
            action=f"tool.{tool_name}",
            subject_type="agent",
            subject_id=agent_name,
            payload=payload,
        )

    def __len__(self) -> int:
        return len(self.names())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self._visible(name)
