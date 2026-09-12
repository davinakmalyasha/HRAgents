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
from typing import Any, Protocol

from hr_agents.models import ActorType, AuditActor, AuditEntry, payload_digest

ToolHandler = Callable[..., Any] | Callable[..., Awaitable[Any]]


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


class ToolPermissionError(PermissionError):
    """Raised when an agent attempts to use a tool it was not granted."""


class ToolNotFoundError(KeyError):
    """Raised when a tool name is unknown to the registry."""


@dataclass(frozen=True)
class ToolDefinition:
    """A governed tool: metadata, permission scope, and the handler."""

    name: str
    description: str
    allowed_agents: frozenset[str]
    handler: ToolHandler
    dry_run_safe: bool = True
    tags: frozenset[str] = field(default_factory=frozenset)

    def permits(self, agent_name: str) -> bool:
        return agent_name.strip().lower() in self.allowed_agents

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
    ) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._audit = audit
        self._scope: frozenset[str] | None = frozenset(scope) if scope is not None else None
        self._scope_id = scope_id

    def scoped(self, tools: Iterable[str], *, scope_id: str | None = None) -> ToolRegistry:
        """A view limited to ``tools``, sharing definitions and the audit sink.

        Scoping an already-scoped view can only narrow it further, never widen.
        """
        narrowed = frozenset(tools)
        if self._scope is not None:
            narrowed &= self._scope
        view = ToolRegistry(self._audit, scope=narrowed, scope_id=scope_id or self._scope_id)
        view._tools = self._tools
        return view

    def register(self, definition: ToolDefinition) -> None:
        if self._scope is not None:
            raise ValueError("cannot register tools into a scoped view")
        if definition.name in self._tools:
            raise ValueError(f"duplicate tool name: {definition.name!r}")
        if not definition.allowed_agents:
            raise ValueError(f"tool {definition.name!r} must declare allowed agents")
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
