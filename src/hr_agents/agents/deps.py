"""Shared agent dependencies — ports injected into every agent run.

Dependencies are deliberately composed of *ports* (protocols/registries) so
tests can inject fakes and production can swap backends without touching agent
code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hr_agents.services.audit import AuditChain
from hr_agents.tools.registry import ToolRegistry


@dataclass(slots=True)
class AgentDeps:
    """Runtime dependencies available to agent tools via RunContext."""

    tools: ToolRegistry
    audit: AuditChain = field(default_factory=AuditChain)
    knowledge_namespaces: tuple[str, ...] = ()
    request_id: str = ""

    def namespaced(self, *namespaces: str) -> AgentDeps:
        """Return a copy scoped to the given knowledge namespaces."""
        return AgentDeps(
            tools=self.tools,
            audit=self.audit,
            knowledge_namespaces=tuple(namespaces),
            request_id=self.request_id,
        )
