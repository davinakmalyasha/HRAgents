"""Chat service: routing provenance, grounding enforcement, conversation history."""

from uuid import uuid4

import pytest

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.policy_assistant import PolicyAnswer, PolicyResult
from hr_agents.rbac import Principal, RoleId
from hr_agents.services.audit import AuditChain
from hr_agents.services.chat import (
    ESCALATION_TEXT,
    ChatError,
    ChatService,
    ChatWorkspaceMismatch,
)
from hr_agents.services.front_door import FrontDoor
from hr_agents.tools import ToolDefinition, ToolNotFoundError, ToolRegistry
from hr_agents.workspaces import WorkspaceId

PRINCIPAL = Principal(actor_id="hr-admin", role=RoleId.HR_ADMIN)


class FakeResponder:
    def __init__(self, answer: PolicyAnswer) -> None:
        self._answer = answer
        self.deps_history: list[AgentDeps] = []
        self.questions: list[str] = []

    async def ask(self, question: str, *, deps: AgentDeps) -> PolicyResult:
        self.questions.append(question)
        self.deps_history.append(deps)
        return PolicyResult(answer=self._answer)


def make_service(answer: PolicyAnswer) -> tuple[ChatService, FakeResponder, AuditChain]:
    audit = AuditChain()
    responder = FakeResponder(answer)
    service = ChatService(
        front_door=FrontDoor(),
        responder=responder,
        audit=audit,
        tools=ToolRegistry(audit=audit),
    )
    return service, responder, audit


async def test_grounded_answer_is_returned_with_routing_provenance() -> None:
    answer = PolicyAnswer(
        answer="Saldo cuti tahunan Anda 12 hari.",
        citations=["leave-policy.md#saldo"],
        confidence=0.8,
    )
    service, _, audit = make_service(answer)

    reply = await service.ask(message="berapa saldo cuti saya?", principal=PRINCIPAL)

    assert reply.workspace is WorkspaceId.LEAVE
    assert reply.route_reason.value == "keyword"
    assert reply.answer == answer.answer
    assert reply.citations == ["leave-policy.md#saldo"]
    assert reply.escalate is False
    actions = [entry.action for entry in audit.entries]
    assert "chat.answered" in actions
    assert "chat.escalated" not in actions


async def test_uncited_answer_is_replaced_by_escalation() -> None:
    answer = PolicyAnswer(answer="Saya pikir cutinya 20 hari.", citations=[])
    service, _, audit = make_service(answer)

    reply = await service.ask(message="berapa saldo cuti saya?", principal=PRINCIPAL)

    assert reply.answer == ESCALATION_TEXT
    assert reply.escalate is True
    assert reply.citations == []
    actions = [entry.action for entry in audit.entries]
    assert "chat.escalated" in actions


async def test_conversation_history_is_workspace_scoped_and_continuous() -> None:
    answer = PolicyAnswer(answer="Kebijakan cuti ada di dokumen.", citations=["policy.md#1"])
    service, responder, _ = make_service(answer)

    first = await service.ask(message="berapa saldo cuti saya?", principal=PRINCIPAL)
    second = await service.ask(
        message="bagaimana aturan cuti tahunan?",
        principal=PRINCIPAL,
        conversation_id=first.conversation_id,
    )
    assert second.conversation_id == first.conversation_id

    record = service.get_conversation(first.conversation_id)
    assert record is not None
    assert record.workspace is WorkspaceId.LEAVE
    assert len(record.turns) == 4
    assert [turn.role for turn in record.turns] == ["user", "assistant", "user", "assistant"]

    deps = responder.deps_history[0]
    assert deps.knowledge_namespaces == ("platform.knowledge",)


async def test_conversation_cannot_cross_workspaces() -> None:
    answer = PolicyAnswer(answer="Kebijakan cuti ada di dokumen.", citations=["policy.md#1"])
    service, _, _ = make_service(answer)

    first = await service.ask(message="berapa saldo cuti saya?", principal=PRINCIPAL)
    with pytest.raises(ChatWorkspaceMismatch):
        await service.ask(
            message="kapan gaji dibayar?",
            principal=PRINCIPAL,
            conversation_id=first.conversation_id,
        )

    record = service.get_conversation(first.conversation_id)
    assert record is not None
    assert len(record.turns) == 2


async def test_cross_workspace_matches_are_offered_as_handoff_options() -> None:
    answer = PolicyAnswer(answer="Dua urusan terdeteksi.", citations=["policy.md#1"])
    service, _, _ = make_service(answer)

    reply = await service.ask(
        message="tolong siapkan onboarding untuk Budi dan cek gaji serta THR",
        principal=PRINCIPAL,
    )

    assert reply.workspace is WorkspaceId.PAYROLL
    assert WorkspaceId.ONBOARDING in reply.handoff_options


async def test_workspace_run_gets_scoped_tool_view() -> None:
    answer = PolicyAnswer(answer="ok", citations=["policy.md#1"])
    audit = AuditChain()
    responder = FakeResponder(answer)

    def handler() -> str:
        return "ok"

    tools = ToolRegistry(audit=audit)
    tools.register(
        ToolDefinition(
            name="search_knowledge",
            description="fake",
            allowed_agents=frozenset({"policy_assistant"}),
            handler=handler,
        )
    )
    tools.register(
        ToolDefinition(
            name="github_profile",
            description="fake",
            allowed_agents=frozenset({"policy_assistant"}),
            handler=handler,
        )
    )
    service = ChatService(front_door=FrontDoor(), responder=responder, audit=audit, tools=tools)

    await service.ask(message="berapa saldo cuti saya?", principal=PRINCIPAL)

    scoped = responder.deps_history[0].tools
    assert scoped.names() == ["search_knowledge"]
    with pytest.raises(ToolNotFoundError):
        scoped.get("github_profile")


async def test_unknown_conversation_is_rejected() -> None:
    answer = PolicyAnswer(answer="ok", citations=["policy.md#1"])
    service, _, _ = make_service(answer)
    with pytest.raises(ChatError):
        await service.ask(
            message="hai",
            principal=PRINCIPAL,
            conversation_id=uuid4(),
        )


async def test_explicit_workspace_overrides_keywords() -> None:
    answer = PolicyAnswer(answer="Payroll diproses setiap bulan.", citations=["payroll.md#1"])
    service, responder, _ = make_service(answer)

    reply = await service.ask(
        message="berapa saldo cuti saya?",
        principal=PRINCIPAL,
        workspace=WorkspaceId.PAYROLL,
    )

    assert reply.workspace is WorkspaceId.PAYROLL
    assert reply.route_reason.value == "explicit"
    assert responder.deps_history[0].knowledge_namespaces == ("platform.knowledge",)
