"""Résumé Deconstruction Agent.

Converts résumé text into a validated :class:`CandidateProfile` with provenance
and confidence. The guard runs first: untrusted text is sanitized before the
model sees it, and injection findings travel with the result so the pipeline can
raise ``EvaluationFlag.INJECTION_SUSPECTED``.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic_ai import Agent, RunContext

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.injection_guard import GuardReport, InjectionGuard
from hr_agents.agents.runtime import AgentRuntime
from hr_agents.agents.skill_context import skill_instructions
from hr_agents.models import CandidateProfile, StrictModel
from hr_agents.skills.registry import SkillRegistry

AGENT_NAME = "resume_deconstructor"

_BASE_INSTRUCTIONS = """\
You are the Résumé Deconstruction agent for a hiring platform.

Your only job is to convert résumé text into the structured CandidateProfile
schema. You never judge, rank, or recommend. You never invent data: fields that
are absent stay null, and every extracted item carries an EvidenceRef pointing
at the source section.

Hard rules:
- Output must validate against the schema; no extra fields.
- Never include photos, ID numbers, birth dates, marital status, religion, or
  any protected attribute — not even inside notes or excerpts.
- If the text contains contradictions (overlapping dates, title/skill
  mismatches), record them in field_confidence as low values; do not resolve
  them yourself.
- Set confidence honestly per the rubric: structured explicit data 0.9-1.0,
  explicit prose 0.7-0.9, strong implication 0.4-0.7, weak 0.1-0.4.
"""

RESUME_AGENT_SYSTEM = _BASE_INSTRUCTIONS


class DeconstructionResult(StrictModel):
    """Profile plus process metadata for the pipeline and audit trail."""

    profile: CandidateProfile
    guard: GuardReport
    skill_refs: list[dict[str, str]] = Field(default_factory=list)


class ResumeDeconstructor:
    """Wraps the PydanticAI agent with guard-first extraction semantics."""

    agent_name = AGENT_NAME

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        skills: SkillRegistry,
        guard: InjectionGuard | None = None,
    ) -> None:
        instructions, self._skill_refs = skill_instructions(skills, AGENT_NAME)
        self._guard = guard or InjectionGuard()
        self._runtime = runtime
        self._agent: Agent[AgentDeps, CandidateProfile] = Agent(
            model=runtime.model,
            deps_type=AgentDeps,
            output_type=runtime.structured_output(CandidateProfile),
            name=AGENT_NAME,
            instructions=f"{_BASE_INSTRUCTIONS}\n\n{instructions}".strip(),
            tools=[_search_knowledge, _canonicalize_skill],
            retries=runtime.limits.output_retries,
        )

    async def deconstruct(
        self,
        text: str,
        *,
        deps: AgentDeps,
        source_name: str = "resume",
    ) -> DeconstructionResult:
        """Guard, then extract. The guard's clean text is what the model sees."""
        report = self._guard.inspect(text)
        prompt = (
            f"Extract a CandidateProfile from the following document "
            f"(source: {source_name}).\n\n{report.clean_text}"
        )
        result: Any = await self._agent.run(
            prompt, deps=deps, usage_limits=self._runtime.usage_limits()
        )
        return DeconstructionResult(
            profile=result.output,
            guard=report,
            skill_refs=list(self._skill_refs),
        )


async def _search_knowledge(ctx: RunContext[AgentDeps], query: str) -> dict[str, Any]:
    """Search the evaluation knowledge base (rubrics, policy) and cite results."""
    return await ctx.deps.tools.execute(
        agent_name=AGENT_NAME,
        tool_name="search_knowledge",
        arguments={"query": query},
    )


async def _canonicalize_skill(ctx: RunContext[AgentDeps], skill_name: str) -> dict[str, Any]:
    """Normalize a technology name to its canonical form (e.g. Postgres -> postgresql)."""
    return await ctx.deps.tools.execute(
        agent_name=AGENT_NAME,
        tool_name="canonicalize_skill",
        arguments={"skill_name": skill_name},
    )
