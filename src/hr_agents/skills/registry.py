"""Skill registry: indexed lookup by id, department, agent, and knowledge namespace."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.skills.loader import library_fingerprint
from hr_agents.skills.models import KnowledgeDoc, LoadedSkill, SkillManifest


class SkillLibrary(StrictModel):
    """A validated, indexed collection of skills and knowledge documents."""

    skills: list[LoadedSkill] = Field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return library_fingerprint(self.skills)

    @property
    def knowledge(self) -> list[KnowledgeDoc]:
        return [doc for skill in self.skills for doc in skill.knowledge]

    def registry(self) -> SkillRegistry:
        return SkillRegistry(self.skills)


class SkillRegistry:
    """Query interface over a loaded skill library."""

    def __init__(self, skills: Iterable[LoadedSkill]) -> None:
        self._skills: dict[str, LoadedSkill] = {}
        for skill in skills:
            if skill.id in self._skills:
                raise ValueError(f"duplicate skill id: {skill.id}")
            self._skills[skill.id] = skill

    # --- skills ---------------------------------------------------------

    def get(self, skill_id: str) -> LoadedSkill:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise KeyError(f"unknown skill id: {skill_id!r}") from exc

    def all(self) -> list[LoadedSkill]:
        return [self._skills[key] for key in sorted(self._skills)]

    def manifests(self) -> list[SkillManifest]:
        return [skill.manifest for skill in self.all()]

    def for_agent(self, agent_name: str) -> list[LoadedSkill]:
        """Skills whose manifest explicitly allows ``agent_name``."""
        normalized = agent_name.strip().lower()
        return [skill for skill in self.all() if normalized in skill.manifest.agents]

    def for_department(self, department: str) -> list[LoadedSkill]:
        return [skill for skill in self.all() if skill.manifest.department == department]

    # --- knowledge ------------------------------------------------------

    def knowledge(self) -> list[KnowledgeDoc]:
        return [doc for skill in self.all() for doc in skill.knowledge]

    def knowledge_namespaces(self) -> list[str]:
        return sorted({doc.namespace for doc in self.knowledge()})

    def knowledge_for(self, namespace_prefix: str) -> list[KnowledgeDoc]:
        """Documents whose namespace equals or extends ``namespace_prefix``."""
        prefix = namespace_prefix.strip()
        return [
            doc
            for doc in self.knowledge()
            if doc.namespace == prefix or doc.namespace.startswith(prefix + ".")
        ]

    # --- audit ----------------------------------------------------------

    def fingerprint(self) -> str:
        return library_fingerprint(self._skills.values())

    def audit_refs(self) -> list[dict[str, str]]:
        return [skill.audit_ref() for skill in self.all()]

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, skill_id: object) -> bool:
        return isinstance(skill_id, str) and skill_id in self._skills


def registry_from(skills: Sequence[LoadedSkill]) -> SkillRegistry:
    return SkillRegistry(skills)
