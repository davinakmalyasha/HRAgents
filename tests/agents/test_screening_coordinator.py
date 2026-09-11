from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from hr_agents.agents import AgentDeps, AgentRuntime
from hr_agents.agents.screening_coordinator import (
    AGENT_NAME,
    ScreeningCoordinator,
    validate_reply,
)
from hr_agents.knowledge import KnowledgeRetriever
from hr_agents.models import ConversationState, ScreeningAction, ScreeningReply
from hr_agents.services.audit import AuditChain
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.tools import (
    ToolRegistry,
    make_capture_consent_tool,
    make_escalate_to_human_tool,
    make_get_candidate_profile_tool,
    make_record_availability_tool,
    make_search_knowledge_tool,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


def base_reply(**overrides: object) -> ScreeningReply:
    defaults: dict[str, object] = {
        "message": "Terima kasih! Boleh saya tahu ketersediaan Anda minggu depan?",
        "next_state": ConversationState.COLLECTING_AVAILABILITY,
        "actions": [],
        "needs_human": False,
    }
    defaults.update(overrides)
    return ScreeningReply(**defaults)  # type: ignore[arg-type]


# --- deterministic validator ------------------------------------------------


def test_valid_transition_from_consent_passes() -> None:
    violations = validate_reply(base_reply(), current_state=ConversationState.AWAITING_CONSENT)
    assert violations == []


def test_illegal_state_transition_detected() -> None:
    reply = base_reply(next_state=ConversationState.COMPLETE)
    violations = validate_reply(reply, current_state=ConversationState.AWAITING_CONSENT)
    assert any("illegal state transition" in violation for violation in violations)


def test_same_state_stay_is_allowed() -> None:
    reply = base_reply(
        message="Bisa dijelaskan ulang?", next_state=ConversationState.AWAITING_CONSENT
    )
    assert validate_reply(reply, current_state=ConversationState.AWAITING_CONSENT) == []


@pytest.mark.parametrize(
    "message",
    [
        "You got the job!",
        "We regret to inform you that...",
        "The salary is 10 million.",
        "Anda diterima untuk posisi ini.",
    ],
)
def test_banned_phrases_detected(message: str) -> None:
    reply = base_reply(message=message)
    violations = validate_reply(reply, current_state=ConversationState.AWAITING_CONSENT)
    assert any("banned phrase" in violation for violation in violations)


@pytest.mark.parametrize(
    "message",
    [
        "Berapa usia Anda?",
        "Are you married?",
        "Apakah Anda sedang hamil?",
    ],
)
def test_protected_topics_detected(message: str) -> None:
    reply = base_reply(message=message)
    violations = validate_reply(reply, current_state=ConversationState.AWAITING_CONSENT)
    assert any("protected-topic" in violation for violation in violations)


def test_handoff_requires_escalation_action() -> None:
    reply = base_reply(
        message="A human will follow up.",
        next_state=ConversationState.HANDED_OFF_TO_HUMAN,
        needs_human=True,
        actions=[],
    )
    violations = validate_reply(reply, current_state=ConversationState.COLLECTING_AVAILABILITY)
    assert any("escalate_to_human" in violation for violation in violations)


def test_handoff_with_escalation_action_passes() -> None:
    reply = base_reply(
        message="A human will follow up within one business day.",
        next_state=ConversationState.HANDED_OFF_TO_HUMAN,
        needs_human=True,
        actions=[ScreeningAction.ESCALATED],
    )
    violations = validate_reply(reply, current_state=ConversationState.COLLECTING_AVAILABILITY)
    assert violations == []


def test_needs_human_must_handoff() -> None:
    reply = base_reply(needs_human=True, next_state=ConversationState.COLLECTING_AVAILABILITY)
    violations = validate_reply(reply, current_state=ConversationState.COLLECTING_AVAILABILITY)
    assert any("needs_human" in violation for violation in violations)


# --- agent integration ------------------------------------------------------


@pytest.fixture
def skills() -> SkillRegistry:
    return SkillRegistry(load_library(SKILLS_ROOT))


@pytest.fixture
async def deps(skills: SkillRegistry) -> AgentDeps:
    retriever = await KnowledgeRetriever.build(skills.knowledge())
    tools = ToolRegistry(audit=AuditChain())
    tools.register(
        make_search_knowledge_tool(
            retriever, namespaces=["recruiting.screening", "platform.compliance"]
        )
    )
    tools.register(
        make_capture_consent_tool(lambda cid, granted: {"candidate": cid, "granted": granted})
    )
    tools.register(
        make_record_availability_tool(
            lambda cid, availability: {"candidate": cid, "recorded": True}
        )
    )
    tools.register(make_escalate_to_human_tool(lambda cid, reason: {"escalated": True}))
    tools.register(
        make_get_candidate_profile_tool(
            lambda cid: {"candidate_id": cid, "headline": "Backend Engineer"}
        )
    )
    return AgentDeps(tools=tools)


async def test_respond_returns_validated_turn(skills: SkillRegistry, deps: AgentDeps) -> None:
    agent = ScreeningCoordinator(AgentRuntime(TestModel(call_tools=[])), skills=skills)
    result = await agent.respond(
        candidate_message="Saya setuju dengan prosesnya. Kapan wawancaranya?",
        current_state=ConversationState.AWAITING_CONSENT,
        candidate_id="cand-1",
        deps=deps,
    )

    assert isinstance(result.reply, ScreeningReply)
    assert result.skill_refs
    assert "recruiting.screening" in {ref["skill_id"] for ref in result.skill_refs}


async def test_agent_name_constant() -> None:
    assert AGENT_NAME == "screening_coordinator"
    assert ScreeningCoordinator.agent_name == AGENT_NAME
