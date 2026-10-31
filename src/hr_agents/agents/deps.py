"""Shared agent dependencies — ports injected into every agent run.

Dependencies are deliberately composed of *ports* (protocols/registries) so
tests can inject fakes and production can swap backends without touching agent
code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.services.audit import AuditChain
from hr_agents.tools.registry import ToolRegistry
from hr_agents.workspaces import WorkspaceDefinition


class ToolCall(StrictModel):
    """One tool an agent used during a turn, for the transcript's 'what it read'."""

    agent: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=120)


@dataclass(slots=True)
class AgentDeps:
    """Runtime dependencies available to agent tools via RunContext."""

    tools: ToolRegistry
    audit: AuditChain = field(default_factory=AuditChain)
    knowledge_namespaces: tuple[str, ...] = ()
    request_id: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    async def call_tool(
        self,
        *,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Execute through the registry and remember the call for this turn.

        The audit chain records every call but not the conversation that asked,
        so a UI wanting "what it read" would have to scan the whole chain per
        message. The list is per turn and shared by copies of these deps
        (``namespaced``/``for_workspace``), so a scoped tool still counts.
        """
        try:
            return await self.tools.execute(
                agent_name=agent_name, tool_name=tool_name, arguments=arguments
            )
        finally:
            # A refused or failing call is still something the person should see:
            # "it tried to read X and was not allowed" is the honest line.
            self.tool_calls.append(ToolCall(agent=agent_name, tool=tool_name))

    def namespaced(self, *namespaces: str) -> AgentDeps:
        """Return a copy scoped to the given knowledge namespaces."""
        return AgentDeps(
            tools=self.tools,
            audit=self.audit,
            knowledge_namespaces=tuple(namespaces),
            request_id=self.request_id,
            tool_calls=self.tool_calls,
        )

    def for_workspace(self, definition: WorkspaceDefinition) -> AgentDeps:
        """Return a copy scoped to one workspace's tools and knowledge namespaces."""
        return AgentDeps(
            tools=self.tools.scoped(definition.tools, scope_id=definition.id.value),
            audit=self.audit,
            knowledge_namespaces=tuple(sorted(definition.knowledge_namespaces)),
            request_id=self.request_id,
            tool_calls=self.tool_calls,
        )
