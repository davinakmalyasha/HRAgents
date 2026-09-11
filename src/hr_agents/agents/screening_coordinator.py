"""Screening Coordinator Agent.

Runs async candidate conversations: consent capture, availability collection,
profile clarifications, escalation. A deterministic validator enforces the
communication contract (no promises, no rejection language, no protected
topics, valid state transitions) before any message leaves the system.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic_ai import Agent, RunContext

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.runtime import AgentRuntime
from hr_agents.agents.skill_context import skill_instructions
from hr_agents.models import (
    ConversationState,
    ScreeningReply,
    StrictModel,
)
from hr_agents.skills.registry import SkillRegistry

AGENT_NAME = "screening_coordinator"

# Allowed conversation transitions (deterministic guard).
ALLOWED_TRANSITIONS: dict[ConversationState, frozenset[ConversationState]] = {
    ConversationState.AWAITING_CONSENT: frozenset(
        {
            ConversationState.COLLECTING_AVAILABILITY,
            ConversationState.HANDED_OFF_TO_HUMAN,
        }
    ),
    ConversationState.COLLECTING_AVAILABILITY: frozenset(
        {
            ConversationState.CLARIFYING_PROFILE,
            ConversationState.COMPLETE,
            ConversationState.HANDED_OFF_TO_HUMAN,
        }
    ),
    ConversationState.CLARIFYING_PROFILE: frozenset(
        {
            ConversationState.COLLECTING_AVAILABILITY,
            ConversationState.COMPLETE,
            ConversationState.HANDED_OFF_TO_HUMAN,
        }
    ),
    ConversationState.COMPLETE: frozenset({ConversationState.HANDED_OFF_TO_HUMAN}),
    ConversationState.HANDED_OFF_TO_HUMAN: frozenset(),
}

# Phrases the system may never send, across languages (lowercased substring match).
BANNED_PHRASES: tuple[str, ...] = (
    "you got the job",
    "you're hired",
    "you are hired",
    "you'll definitely",
    "you will definitely",
    "guaranteed",
    "we regret to inform",
    "unfortunately, you",
    "we reject",
    "rejected",
    "salary is",
    "gaji pokok",
    "ditolak",
    "anda diterima",
    "pasti diterima",
)

_PROTECTED_TERMS: tuple[str, ...] = (
    "age",
    "how old",
    "married",
    "marital",
    "religion",
    "pregnant",
    "ethnicity",
    "race",
    "birth date",
    "usia",
    "agama",
    "menikah",
    "hamil",
)

_BASE_INSTRUCTIONS = """\
You are the Screening Coordinator agent. You run one async conversation turn
with a candidate on behalf of a busy HR team.

Hard rules:
- Never promise an outcome ("you got the job", "you'll definitely advance") and
  never mention salary numbers or contract terms. Escalate those questions.
- Never send rejection wording. Rejections are gated by the policy engine and
  are outside your authority.
- Never ask about protected attributes (age, marital status, religion, health,
  family plans, ethnicity). If volunteered, do not record or repeat it.
- No rejection of consent: if the candidate declines consent, acknowledge
  respectfully, mark the conversation escalated, and stop.
- One decision per message, concise, warm, plain language in the candidate's
  language (Bahasa Indonesia or English).
- Perform side effects only through tools (capture_consent,
  record_availability, escalate_to_human) and list them in `actions`.
- Choose `next_state` respecting the state machine; when in doubt, keep the
  current state or escalate.
"""


class ScreeningResult(StrictModel):
    reply: ScreeningReply
    violations: list[str] = Field(default_factory=list)
    skill_refs: list[dict[str, str]] = Field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.violations


def validate_reply(
    reply: ScreeningReply,
    *,
    current_state: ConversationState,
) -> list[str]:
    """Deterministic checks on every outbound screening turn."""
    violations: list[str] = []

    lowered = reply.message.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            violations.append(f"banned phrase in message: {phrase!r}")
    for term in _PROTECTED_TERMS:
        if term in lowered:
            violations.append(f"protected-topic term in message: {term!r}")

    allowed = ALLOWED_TRANSITIONS.get(current_state, frozenset())
    if reply.next_state not in allowed and reply.next_state != current_state:
        violations.append(
            f"illegal state transition: {current_state.value} -> {reply.next_state.value}"
        )

    if reply.needs_human and reply.next_state is not ConversationState.HANDED_OFF_TO_HUMAN:
        violations.append("needs_human replies must transition to handed_off_to_human")

    if reply.next_state is ConversationState.HANDED_OFF_TO_HUMAN:
        from hr_agents.models import ScreeningAction

        if ScreeningAction.ESCALATED not in reply.actions:
            violations.append("handed_off_to_human requires the escalate_to_human action")

    return violations


class ScreeningCoordinator:
    """Wraps the agent plus deterministic turn validation."""

    agent_name = AGENT_NAME

    def __init__(self, runtime: AgentRuntime, *, skills: SkillRegistry) -> None:
        instructions, self._skill_refs = skill_instructions(skills, AGENT_NAME)
        self._runtime = runtime
        self._agent: Agent[AgentDeps, ScreeningReply] = Agent(
            model=runtime.model,
            deps_type=AgentDeps,
            output_type=runtime.structured_output(ScreeningReply),
            name=AGENT_NAME,
            instructions=f"{_BASE_INSTRUCTIONS}\n\n{instructions}".strip(),
            tools=[
                _search_knowledge,
                _capture_consent,
                _record_availability,
                _escalate_to_human,
                _get_candidate_profile,
            ],
            retries=runtime.limits.output_retries,
        )

    async def respond(
        self,
        *,
        candidate_message: str,
        current_state: ConversationState,
        candidate_id: str,
        deps: AgentDeps,
    ) -> ScreeningResult:
        prompt = (
            f"Candidate ID: {candidate_id}\n"
            f"Current conversation state: {current_state.value}\n"
            f"Candidate message:\n{candidate_message}"
        )
        result: Any = await self._agent.run(
            prompt, deps=deps, usage_limits=self._runtime.usage_limits()
        )
        reply: ScreeningReply = result.output
        violations = validate_reply(reply, current_state=current_state)
        return ScreeningResult(
            reply=reply, violations=violations, skill_refs=list(self._skill_refs)
        )


async def _search_knowledge(ctx: RunContext[AgentDeps], query: str) -> dict[str, Any]:
    """Search screening and compliance knowledge; cite it in answers."""
    return await ctx.deps.tools.execute(
        agent_name=AGENT_NAME, tool_name="search_knowledge", arguments={"query": query}
    )


async def _capture_consent(
    ctx: RunContext[AgentDeps], candidate_id: str, granted: bool
) -> dict[str, Any]:
    """Record the candidate's explicit consent decision."""
    return await ctx.deps.tools.execute(
        agent_name=AGENT_NAME,
        tool_name="capture_consent",
        arguments={"candidate_id": candidate_id, "granted": granted},
    )


async def _record_availability(
    ctx: RunContext[AgentDeps], candidate_id: str, availability: dict[str, Any]
) -> dict[str, Any]:
    """Record the candidate's availability windows."""
    return await ctx.deps.tools.execute(
        agent_name=AGENT_NAME,
        tool_name="record_availability",
        arguments={"candidate_id": candidate_id, "availability": availability},
    )


async def _escalate_to_human(
    ctx: RunContext[AgentDeps], candidate_id: str, reason: str
) -> dict[str, Any]:
    """Hand the conversation to a human reviewer."""
    return await ctx.deps.tools.execute(
        agent_name=AGENT_NAME,
        tool_name="escalate_to_human",
        arguments={"candidate_id": candidate_id, "reason": reason},
    )


async def _get_candidate_profile(ctx: RunContext[AgentDeps], candidate_id: str) -> dict[str, Any]:
    """Fetch candidate profile facts for context."""
    return await ctx.deps.tools.execute(
        agent_name=AGENT_NAME,
        tool_name="get_candidate_profile",
        arguments={"candidate_id": candidate_id},
    )
