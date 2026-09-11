"""Skill and knowledge document models."""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from hr_agents.models import StrictModel

SKILL_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_ID_RE = re.compile(SKILL_ID_PATTERN)


class SkillManifest(StrictModel):
    """Validated frontmatter of a SKILL.md file.

    ``extra="forbid"`` (inherited from StrictModel) means typos in frontmatter
    fail loudly at load time instead of being silently ignored.
    """

    id: str = Field(
        pattern=SKILL_ID_PATTERN,
        description="Stable identifier, e.g. 'recruiting.screening'. Never rename casually: "
        "it is recorded in audit trails and used for on-demand capability loading.",
    )
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(
        min_length=1,
        max_length=400,
        description="One line shown to the model in the capability catalog.",
    )
    version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    department: str = Field(
        min_length=1,
        max_length=60,
        pattern=r"^[a-z][a-z0-9_-]*$",
        description="Must match the top-level directory under skills/.",
    )
    agents: list[str] = Field(
        min_length=1,
        description="Explicit allowlist of agent names permitted to use this skill "
        "(least privilege — there is no implicit 'all agents').",
    )
    tags: list[str] = Field(default_factory=list)
    defer_loading: bool = Field(
        default=True,
        description="True = progressive disclosure via the capability catalog. "
        "False = instructions always in the system prompt (use sparingly).",
    )

    @field_validator("agents")
    @classmethod
    def _normalize_agents(cls, value: list[str]) -> list[str]:
        normalized = [agent.strip().lower() for agent in value]
        if any(not agent for agent in normalized):
            raise ValueError("agent names must be non-empty")
        return sorted(set(normalized))

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        return sorted({tag.strip().lower() for tag in value if tag.strip()})


class KnowledgeDoc(StrictModel):
    """A markdown knowledge document retrieved via RAG, scoped to a namespace."""

    id: str = Field(pattern=SKILL_ID_PATTERN)
    title: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=60)
    namespace: str = Field(
        min_length=1,
        description="Retrieval scope, e.g. 'recruiting.evaluation'. "
        "Agents can only retrieve from their permitted namespaces.",
    )
    tags: list[str] = Field(default_factory=list)
    source_path: str = Field(min_length=1)
    content: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)


class LoadedSkill(StrictModel):
    """A fully loaded skill: manifest + instructions + knowledge + hash."""

    manifest: SkillManifest
    instructions: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    source_path: str = Field(min_length=1)
    knowledge: list[KnowledgeDoc] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def knowledge_namespaces(self) -> list[str]:
        return sorted({doc.namespace for doc in self.knowledge})

    def audit_ref(self) -> dict[str, str]:
        """The reference recorded in extraction metadata / audit entries."""
        return {
            "skill_id": self.manifest.id,
            "version": self.manifest.version,
            "hash": self.content_hash,
        }
