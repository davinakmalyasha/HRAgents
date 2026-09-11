"""Compose agent instructions from the skill library.

Skills are content: agent behavior lives in ``skills/**/SKILL.md``. This module
turns the skills allowed for an agent into instruction text plus audit refs, so
every run can record exactly which skill versions shaped the output.
"""

from __future__ import annotations

from hr_agents.skills.registry import SkillRegistry

_SEPARATOR = "\n\n---\n\n"


def skill_instructions(
    registry: SkillRegistry, agent_name: str
) -> tuple[str, list[dict[str, str]]]:
    """Return ``(instructions, audit_refs)`` for the agent's allowed skills."""
    skills = registry.for_agent(agent_name)
    blocks = [skill.instructions for skill in skills]
    refs = [skill.audit_ref() for skill in skills]
    return _SEPARATOR.join(blocks), refs
