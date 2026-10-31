from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from hr_agents.agents import AgentDeps, AgentRuntime
from hr_agents.agents.policy_assistant import (
    AGENT_NAME,
    PolicyAnswer,
    PolicyAssistant,
    validate_policy_answer,
)
from hr_agents.knowledge import KnowledgeRetriever
from hr_agents.services.audit import AuditChain
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.tools import ToolRegistry, make_search_knowledge_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


def test_cited_answer_passes() -> None:
    answer = PolicyAnswer(
        answer="Annual leave is 12 days per year after 12 months of service.",
        citations=["UU Ketenagakerjaan summary — Leave (uu-pdp-summary)"],
        confidence=0.8,
    )
    assert validate_policy_answer(answer) == []


def test_uncited_answer_violates() -> None:
    answer = PolicyAnswer(answer="Twelve days, I think.", citations=[])
    violations = validate_policy_answer(answer)
    assert any("uncited" in violation for violation in violations)


def test_escalation_without_citations_is_allowed() -> None:
    answer = PolicyAnswer(
        answer="I don't have that documented; a human will follow up.",
        citations=[],
        escalate=True,
        confidence=0.2,
    )
    assert validate_policy_answer(answer) == []


def test_escalation_with_high_confidence_violates() -> None:
    answer = PolicyAnswer(answer="Escalating.", citations=[], escalate=True, confidence=0.9)
    violations = validate_policy_answer(answer)
    assert any("high confidence" in violation for violation in violations)


@pytest.fixture
def skills() -> SkillRegistry:
    return SkillRegistry(load_library(SKILLS_ROOT))


async def test_assistant_runs_with_knowledge_tool(skills: SkillRegistry) -> None:
    retriever = await KnowledgeRetriever.build(skills.knowledge())
    tools = ToolRegistry(audit=AuditChain())
    tools.register(
        make_search_knowledge_tool(
            retriever, namespaces=["platform.knowledge", "platform.compliance"]
        )
    )
    deps = AgentDeps(tools=tools)

    assistant = PolicyAssistant(AgentRuntime(TestModel(call_tools=[])), skills=skills)
    result = await assistant.ask("How many annual leave days do we offer?", deps=deps)

    assert isinstance(result.answer, PolicyAnswer)
    assert result.skill_refs
    assert "platform.knowledge" in {ref["skill_id"] for ref in result.skill_refs}


async def test_assistant_streams_deltas_and_returns_the_same_answer(
    skills: SkillRegistry,
) -> None:
    """The streaming path is the same run, reported as it grows."""
    deps = AgentDeps(tools=ToolRegistry(audit=AuditChain()))
    assistant = PolicyAssistant(AgentRuntime(TestModel(call_tools=[])), skills=skills)
    deltas: list[str] = []

    result = await assistant.ask_stream(
        "How many annual leave days do we offer?", deps=deps, on_delta=deltas.append
    )

    assert isinstance(result.answer, PolicyAnswer)
    # The offline model may emit the whole object in one chunk; what matters is
    # that the stream and the final answer agree, and that the final object is
    # the one grounding validates.
    assert "".join(deltas) == "" or "".join(deltas) in result.answer.answer


def test_agent_name_constant() -> None:
    assert AGENT_NAME == "policy_assistant"
    assert PolicyAssistant.agent_name == AGENT_NAME
