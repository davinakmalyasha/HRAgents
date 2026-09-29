"""Agent composition root — the single place every agent is constructed.

The API server, the worker CLI, and the scheduler all build through here so the
same skill library, knowledge namespaces, tool registry, and audit chain apply in
every process. A missing skills root is a loud failure, never a silent
degradation: an absent library means every agent loses its runbooks, so it must
be visible at startup rather than discovered by a user mid-queue.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hr_agents.agents.code_portfolio import CodePortfolioEvaluator
from hr_agents.agents.feedback_writer import FeedbackWriter
from hr_agents.agents.policy_assistant import PolicyAssistant
from hr_agents.agents.resume_deconstructor import ResumeDeconstructor
from hr_agents.agents.runtime import AgentRuntime
from hr_agents.agents.screening_coordinator import ScreeningCoordinator
from hr_agents.knowledge import KnowledgeRetriever
from hr_agents.services.audit import AuditChain
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.tools import (
    ToolRegistry,
    make_canonicalize_skill_tool,
    make_search_knowledge_tool,
)
from hr_agents.workspaces import default_registry


class KnowledgeUnavailableError(RuntimeError):
    """The skills root is missing or unreadable — agents cannot be built safely."""


def resolve_skills_root(configured: str | Path | None = None) -> Path:
    """Locate the ``skills/`` library.

    Order: explicit argument, ``HRAGENTS_SKILLS_ROOT``, then the repository root
    inferred from this file. Raises when the directory does not exist so a
    truncated container image fails at startup instead of returning 503s later.
    """
    import os

    env = os.environ.get("HRAGENTS_SKILLS_ROOT")
    root = (
        Path(configured)
        if configured is not None
        else (Path(env) if env else Path(__file__).resolve().parents[2] / "skills")
    )
    if not root.is_dir():
        raise KnowledgeUnavailableError(
            f"skills root {root} does not exist — set HRAGENTS_SKILLS_ROOT to the "
            "directory containing recruiting/ and platform/ skill packs"
        )
    return root


@dataclass(slots=True)
class AgentSet:
    """Every agent plus the shared tools and knowledge they are scoped with."""

    runtime: AgentRuntime
    skills: SkillRegistry
    tools: ToolRegistry
    retriever: KnowledgeRetriever
    namespaces: tuple[str, ...]
    resume: ResumeDeconstructor
    portfolio: CodePortfolioEvaluator
    screening: ScreeningCoordinator
    feedback: FeedbackWriter
    policy: PolicyAssistant

    @property
    def agent_names(self) -> tuple[str, ...]:
        return (
            self.resume.agent_name,
            self.portfolio.agent_name,
            self.screening.agent_name,
            self.feedback.agent_name,
            self.policy.agent_name,
        )


async def build_agent_set(
    *,
    audit: AuditChain,
    runtime: AgentRuntime | None = None,
    skills_root: str | Path | None = None,
) -> AgentSet:
    """Load the skill library, build the retriever, and instantiate all five agents."""
    root = resolve_skills_root(skills_root)
    skills = SkillRegistry(load_library(root))
    retriever = await KnowledgeRetriever.build(skills.knowledge())

    registry = default_registry()
    namespaces = tuple(
        sorted({ns for item in registry.list_all() for ns in item.knowledge_namespaces})
    )

    tools = ToolRegistry(audit=audit)
    tools.register(make_search_knowledge_tool(retriever, namespaces=list(namespaces)))
    tools.register(make_canonicalize_skill_tool())

    resolved = runtime or AgentRuntime.from_env()

    return AgentSet(
        runtime=resolved,
        skills=skills,
        tools=tools,
        retriever=retriever,
        namespaces=namespaces,
        resume=ResumeDeconstructor(resolved, skills=skills),
        portfolio=CodePortfolioEvaluator(resolved, skills=skills),
        screening=ScreeningCoordinator(resolved, skills=skills),
        feedback=FeedbackWriter(resolved, skills=skills),
        policy=PolicyAssistant(resolved, skills=skills),
    )
