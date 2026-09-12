"""Ask HR: front-door routing, grounded answers, and conversation history.

Answers come from the Policy Assistant only through retrieved citations. When
grounding validation fails, deterministic code replaces the answer with an
escalation — an ungrounded answer is never shown to a user.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.policy_assistant import PolicyResult, validate_policy_answer
from hr_agents.models import ActorType, AuditActor, StrictModel, UtcDateTime, utc_now
from hr_agents.rbac import Principal
from hr_agents.services.audit import AuditChain
from hr_agents.services.front_door import FrontDoor, RouteDecision, RouteReason
from hr_agents.tools.registry import ToolRegistry
from hr_agents.workspaces import WorkspaceId

ESCALATION_TEXT = "I could not ground an answer in the current policies, so a human will follow up."


class ChatError(RuntimeError):
    """Raised for invalid chat operations (unknown conversation, etc.)."""


class ChatWorkspaceMismatch(ChatError):
    """Raised when a conversation is continued from a different workspace."""


class ChatTurn(StrictModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)
    at: UtcDateTime = Field(default_factory=utc_now)


class ConversationRecord(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    workspace: WorkspaceId
    turns: list[ChatTurn] = Field(default_factory=list)
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)


class ConversationStore:
    """In-memory conversation history behind persistence primitives."""

    def __init__(self) -> None:
        self._items: dict[UUID, ConversationRecord] = {}

    def _load(self, conversation_id: UUID) -> ConversationRecord | None:
        return self._items.get(conversation_id)

    def _persist(self, record: ConversationRecord) -> None:
        self._items[record.id] = record

    def _iter(self) -> Iterator[ConversationRecord]:
        return iter(self._items.values())

    def get(self, conversation_id: UUID) -> ConversationRecord | None:
        return self._load(conversation_id)

    def list_all(self) -> list[ConversationRecord]:
        return sorted(self._iter(), key=lambda item: item.updated_at)


class PolicyResponder(Protocol):
    """Port for the policy assistant (real agent or a deterministic fake)."""

    async def ask(self, question: str, *, deps: AgentDeps) -> PolicyResult: ...


class ChatReply(StrictModel):
    """One answered exchange, with routing and grounding provenance."""

    conversation_id: UUID
    workspace: WorkspaceId
    route_reason: RouteReason
    matched_keywords: list[str] = Field(default_factory=list)
    handoff_options: list[WorkspaceId] = Field(default_factory=list)
    answer: str
    citations: list[str] = Field(default_factory=list)
    escalate: bool = False


class ChatService:
    """Routes messages, runs the policy responder, and stores the conversation."""

    def __init__(
        self,
        *,
        front_door: FrontDoor,
        responder: PolicyResponder,
        audit: AuditChain,
        tools: ToolRegistry,
        conversations: ConversationStore | None = None,
    ) -> None:
        self._front_door = front_door
        self._responder = responder
        self._audit = audit
        self._tools = tools
        self._conversations = conversations or ConversationStore()

    def get_conversation(self, conversation_id: UUID) -> ConversationRecord | None:
        return self._conversations.get(conversation_id)

    async def ask(
        self,
        *,
        message: str,
        principal: Principal,
        workspace: WorkspaceId | None = None,
        conversation_id: UUID | None = None,
    ) -> ChatReply:
        decision: RouteDecision = self._front_door.route(message, workspace=workspace)
        definition = self._front_door.registry.get(decision.workspace)

        record = self._conversations.get(conversation_id) if conversation_id else None
        if conversation_id is not None and record is None:
            raise ChatError(f"unknown conversation {conversation_id}")
        if record is None:
            record = ConversationRecord(workspace=decision.workspace)
        elif record.workspace is not decision.workspace:
            raise ChatWorkspaceMismatch(
                f"conversation {record.id} belongs to workspace "
                f"{record.workspace.value!r}, not {decision.workspace.value!r}"
            )
        record.turns.append(ChatTurn(role="user", text=message))

        deps = AgentDeps(
            tools=self._tools,
            audit=self._audit,
            request_id=str(record.id),
        ).for_workspace(definition)

        result = await self._responder.ask(message, deps=deps)

        violations = sorted(set(result.violations) | set(validate_policy_answer(result.answer)))
        if not violations:
            answer = result.answer.answer
            citations = list(result.answer.citations)
            escalate = result.answer.escalate
        else:
            answer = ESCALATION_TEXT
            citations = []
            escalate = True
            self._audit.append_system(
                action="chat.escalated",
                subject_type="conversation",
                subject_id=str(record.id),
                payload={
                    "workspace": decision.workspace.value,
                    "violations": violations,
                },
            )

        record.turns.append(ChatTurn(role="assistant", text=answer))
        record.updated_at = utc_now()
        self._conversations._persist(record)

        self._audit.append(
            actor=self._actor(principal),
            action="chat.answered",
            subject_type="conversation",
            subject_id=str(record.id),
            payload={
                "workspace": decision.workspace.value,
                "route_reason": decision.reason.value,
                "escalate": escalate,
                "citations": len(citations),
            },
        )
        return ChatReply(
            conversation_id=record.id,
            workspace=decision.workspace,
            route_reason=decision.reason,
            matched_keywords=list(decision.matched_keywords),
            handoff_options=list(decision.alternates),
            answer=answer,
            citations=citations,
            escalate=escalate,
        )

    @staticmethod
    def _actor(principal: Principal) -> AuditActor:
        return AuditActor(actor_type=ActorType.HUMAN, actor_id=principal.actor_id)
