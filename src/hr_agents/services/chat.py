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
from hr_agents.errors import DomainError
from hr_agents.identity import ActorRef
from hr_agents.models import AuditActor, StrictModel, UtcDateTime, utc_now
from hr_agents.rbac import Principal, RoleId
from hr_agents.services.audit import AuditChain
from hr_agents.services.front_door import FrontDoor, RouteDecision, RouteReason
from hr_agents.tools.registry import ToolRegistry
from hr_agents.workspaces import WorkspaceId

ESCALATION_TEXT = "I could not ground an answer in the current policies, so a human will follow up."


class ChatError(DomainError, RuntimeError):
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
    owner: str
    """The actor who started this conversation, from the API key.

    The record had no owner at all, so ``GET /v1/chat/conversations/{id}`` was a
    pure IDOR: anyone holding ``chat:use`` -- the *only* permission the
    ``employee`` role has -- could read anyone's HR conversation given the UUID.
    An HR chat contains salaries and medical notes. The id is the only thing that
    was standing between two people, which is not an authorization check.
    """

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

    def get_conversation(
        self, conversation_id: UUID, *, principal: Principal | None = None
    ) -> ConversationRecord | None:
        """One conversation, if the caller is allowed to see it.

        Without a ``principal`` this is an internal read (the agent runtime
        resolving a thread). Over HTTP the caller is always supplied, and a
        conversation belongs to the actor who opened it; an HR admin may read any,
        which is the one deliberate exception and matches every other record in
        the product.
        """
        record = self._conversations.get(conversation_id)
        if record is None or principal is None:
            return record
        if record.owner == principal.actor_id or principal.role is RoleId.HR_ADMIN:
            return record
        # Deliberately indistinguishable from "no such conversation": a caller
        # must not be able to probe for which ids exist.
        return None

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
            record = ConversationRecord(workspace=decision.workspace, owner=principal.actor_id)
        elif record.owner != principal.actor_id and principal.role is not RoleId.HR_ADMIN:
            raise ChatError(f"unknown conversation {conversation_id}")
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
        """The principal as an audit actor, with its provenance and role.

        This used to build `AuditActor(actor_type=ActorType.HUMAN,
        actor_id=principal.actor_id)` directly, which left `provenance` at its
        default of `LEGACY_STRING` and `role` at `None` -- so a chain entry
        produced from an authenticated API key read, to anyone auditing it later,
        exactly like a name typed into a request body. The service comment above
        this method even claimed the opposite.

        `ActorType` was also hardcoded to `HUMAN`, so a principal configured as
        `agent:hr_bot` was recorded as a person answering an HR question.
        `from_principal` classifies instead of asserting, and carries the role.
        """
        return ActorRef.from_principal(principal).audit_actor()
