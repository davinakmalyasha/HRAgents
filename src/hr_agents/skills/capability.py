"""Build PydanticAI capabilities from loaded skills.

A markdown skill becomes an on-demand (deferred) capability: the model sees only
its id + description until it calls ``load_capability``, at which point the full
runbook — and any tools bundled with it — become available. This keeps token
cost flat as the library grows and keeps tool selection accurate.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic_ai.capabilities import Capability
from pydantic_ai.tools import Tool

from hr_agents.skills.models import LoadedSkill

ToolLike = Tool[Any] | Callable[..., Any]


def build_capability(
    skill: LoadedSkill,
    *,
    tools: Sequence[ToolLike] = (),
) -> Capability[Any]:
    """Convert a loaded skill into a PydanticAI capability.

    ``tools`` lets callers bundle skill-specific tools so they activate together
    with the instructions when the capability is loaded.
    """
    return Capability(
        id=skill.manifest.id,
        description=skill.manifest.description,
        instructions=skill.instructions,
        tools=tuple(tools),
        defer_loading=skill.manifest.defer_loading,
    )


def build_capabilities(
    skills: Sequence[LoadedSkill],
    *,
    tools_by_skill: dict[str, Sequence[ToolLike]] | None = None,
) -> list[Capability[Any]]:
    """Convert many skills, optionally attaching per-skill tools by skill id."""
    mapping = tools_by_skill or {}
    return [build_capability(skill, tools=mapping.get(skill.id, ())) for skill in skills]
