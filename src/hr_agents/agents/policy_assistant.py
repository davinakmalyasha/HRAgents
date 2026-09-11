"""Policy Assistant agent — cited answers over company knowledge.

Answers policy and process questions strictly from retrieved knowledge
documents. A deterministic validator enforces the core rule: **cite or
escalate** — no uncited factual answers, ever.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic_ai import Agent, RunContext

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.runtime import AgentRuntime
from hr_agents.agents.skill_context import skill_instructions
from hr_agents.models import StrictModel
from hr_agents.skills.registry import SkillRegistry

AGENT_NAME = "policy_assistant"

_BASE_INSTRUCTIONS = """\
You are the Policy Assistant for a company's HR platform.

You answer questions about policies, processes, and benefits using ONLY the
knowledge base retrieved through the search_knowledge tool.

Hard rules:
- Every factual answer must carry at least one citation from retrieved results.
- If retrieval returns nothing relevant, set escalate=true and say a human will
  follow up. Never improvise, never use general legal knowledge as an answer.
- No legal advice: present the documented policy and note that specific cases
  should be confirmed by the operator or counsel.
- No salary commitments, no contract interpretation beyond the document text.
- Answer in the user's language (English or Bahasa Indonesia), plainly.
"""


class PolicyAnswer(StrictModel):
    """One policy answer with mandatory grounding."""

    answer: str = Field(min_length=1, max_length=4000)
    citations: list[str] = Field(default_factory=list)
    escalate: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PolicyResult(StrictModel):
    answer: PolicyAnswer
    violations: list[str] = Field(default_factory=list)
    skill_refs: list[dict[str, str]] = Field(default_factory=list)

    @property
    def passes_grounding(self) -> bool:
        return not self.violations


def validate_policy_answer(answer: PolicyAnswer) -> list[str]:
    """Cite-or-escalate enforcement (deterministic)."""
    violations: list[str] = []
    if not answer.escalate and not answer.citations:
        violations.append("uncited answer: citations are mandatory unless escalating")
    if answer.escalate and answer.confidence > 0.5:
        violations.append("escalated answers must not claim high confidence")
    return violations


class PolicyAssistant:
    """Wraps the agent plus deterministic grounding validation."""

    agent_name = AGENT_NAME

    def __init__(self, runtime: AgentRuntime, *, skills: SkillRegistry) -> None:
        instructions, self._skill_refs = skill_instructions(skills, AGENT_NAME)
        self._runtime = runtime
        self._agent: Agent[AgentDeps, PolicyAnswer] = Agent(
            model=runtime.model,
            deps_type=AgentDeps,
            output_type=runtime.structured_output(PolicyAnswer),
            name=AGENT_NAME,
            instructions=f"{_BASE_INSTRUCTIONS}\n\n{instructions}".strip(),
            tools=[_search_knowledge],
            retries=runtime.limits.output_retries,
        )

    async def ask(self, question: str, *, deps: AgentDeps) -> PolicyResult:
        result: Any = await self._agent.run(
            f"Question: {question}", deps=deps, usage_limits=self._runtime.usage_limits()
        )
        answer: PolicyAnswer = result.output
        return PolicyResult(
            answer=answer,
            violations=validate_policy_answer(answer),
            skill_refs=list(self._skill_refs),
        )


async def _search_knowledge(ctx: RunContext[AgentDeps], query: str) -> dict[str, Any]:
    """Search the knowledge base; results carry citations."""
    return await ctx.deps.tools.execute(
        agent_name=AGENT_NAME, tool_name="search_knowledge", arguments={"query": query}
    )
