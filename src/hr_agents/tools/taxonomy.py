"""Deterministic taxonomy tools."""

from __future__ import annotations

from hr_agents.services.scoring import normalize_skill
from hr_agents.tools.registry import ToolDefinition


def make_canonicalize_skill_tool() -> ToolDefinition:
    """Build the ``canonicalize_skill`` tool (pure, deterministic)."""

    def canonicalize_skill(skill_name: str) -> dict[str, str]:
        """Normalize a skill name to its canonical form (e.g. 'Postgres' -> 'postgresql')."""
        normalized = normalize_skill(skill_name)
        return {"input": skill_name, "canonical": normalized}

    return ToolDefinition(
        name="canonicalize_skill",
        description=(
            "Normalize a technology or skill name to its canonical form so aliases "
            "(Postgres/PostgreSQL, K8s/Kubernetes) compare correctly."
        ),
        allowed_agents=frozenset({"resume_deconstructor", "code_portfolio"}),
        handler=canonicalize_skill,
        tags=frozenset({"taxonomy", "read", "deterministic"}),
    )
