"""Front door: deterministic workspace routing for chat messages.

Routing is pure selection over the department packs. It never executes,
approves, rejects, or mutates anything consequential — those paths stay behind
their own gates. Ambiguity falls back to Ask HR, and an explicit workspace
hint always wins.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.workspaces import (
    WorkspaceDefinition,
    WorkspaceId,
    WorkspaceRegistry,
    default_registry,
)


class RouteReason(StrEnum):
    EXPLICIT = "explicit"
    KEYWORD = "keyword"
    FALLBACK = "fallback"


class RouteDecision(StrictModel):
    """Which workspace handles one message, and why.

    ``alternates`` lists other keyword-matched departments, best first, so the
    caller can offer an explicit handoff. It is a suggestion surface only: the
    router never executes or transfers anything itself.
    """

    workspace: WorkspaceId
    reason: RouteReason
    matched_keywords: list[str] = Field(default_factory=list)
    alternates: list[WorkspaceId] = Field(default_factory=list)


class FrontDoor:
    """Deterministic keyword router over the workspace packs."""

    def __init__(self, registry: WorkspaceRegistry | None = None) -> None:
        self._registry = registry or default_registry()

    @property
    def registry(self) -> WorkspaceRegistry:
        return self._registry

    def route(self, message: str, *, workspace: WorkspaceId | None = None) -> RouteDecision:
        """Route one message. Invalid explicit workspaces raise ``WorkspaceError``."""
        if workspace is not None:
            definition = self._registry.get(workspace)
            return RouteDecision(workspace=definition.id, reason=RouteReason.EXPLICIT)

        text = " ".join(message.lower().split())
        matches: list[tuple[WorkspaceDefinition, list[str]]] = []
        for definition in self._registry.list_all():
            matched = sorted(keyword for keyword in definition.keywords if keyword in text)
            if matched:
                matches.append((definition, matched))
        ranked = sorted(matches, key=lambda item: (-len(item[1]), self._rank(item[0].id)))

        departments = [item for item in ranked if item[0].id is not WorkspaceId.POLICY]
        if departments:
            definition, matched = departments[0]
            return RouteDecision(
                workspace=definition.id,
                reason=RouteReason.KEYWORD,
                matched_keywords=matched,
                alternates=[item[0].id for item in departments[1:]],
            )
        policy = next((item for item in ranked if item[0].id is WorkspaceId.POLICY), None)
        if policy is not None:
            return RouteDecision(
                workspace=policy[0].id,
                reason=RouteReason.KEYWORD,
                matched_keywords=policy[1],
            )
        return RouteDecision(workspace=WorkspaceId.POLICY, reason=RouteReason.FALLBACK)

    @staticmethod
    def _rank(workspace: WorkspaceId) -> int:
        return list(WorkspaceId).index(workspace)
