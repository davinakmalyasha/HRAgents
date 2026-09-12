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
from hr_agents.workspaces import WorkspaceId, WorkspaceRegistry, default_registry


class RouteReason(StrEnum):
    EXPLICIT = "explicit"
    KEYWORD = "keyword"
    FALLBACK = "fallback"


class RouteDecision(StrictModel):
    """Which workspace handles one message, and why."""

    workspace: WorkspaceId
    reason: RouteReason
    matched_keywords: list[str] = Field(default_factory=list)


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
        best: RouteDecision | None = None
        policy_match: RouteDecision | None = None
        for definition in self._registry.list_all():
            matched = sorted(keyword for keyword in definition.keywords if keyword in text)
            if not matched:
                continue
            candidate = RouteDecision(
                workspace=definition.id,
                reason=RouteReason.KEYWORD,
                matched_keywords=matched,
            )
            if definition.id is WorkspaceId.POLICY:
                policy_match = candidate
                continue
            if best is None or len(matched) > len(best.matched_keywords):
                best = candidate
        if best is not None:
            return best
        if policy_match is not None:
            return policy_match
        return RouteDecision(workspace=WorkspaceId.POLICY, reason=RouteReason.FALLBACK)
