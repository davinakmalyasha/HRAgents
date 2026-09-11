"""Skill system: markdown skills, knowledge documents, and capability building.

Skills are content (markdown with YAML frontmatter); this package turns them into
validated, versioned, hash-tracked PydanticAI capabilities. Editing a skill file
is the entire skill-development workflow — no code changes required.
"""

from hr_agents.skills.capability import build_capability
from hr_agents.skills.loader import (
    SkillFormatError,
    discover_skill_paths,
    load_library,
    load_skill,
)
from hr_agents.skills.models import KnowledgeDoc, LoadedSkill, SkillManifest
from hr_agents.skills.registry import SkillLibrary, SkillRegistry

__all__ = [
    "KnowledgeDoc",
    "LoadedSkill",
    "SkillFormatError",
    "SkillLibrary",
    "SkillManifest",
    "SkillRegistry",
    "build_capability",
    "discover_skill_paths",
    "load_library",
    "load_skill",
]
