"""API models for Ask HR chat."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.services.chat import ChatReply, ChatTurn, ConversationRecord
from hr_agents.services.front_door import RouteReason
from hr_agents.workspaces import WorkspaceId


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    workspace: WorkspaceId | None = None
    conversation_id: UUID | None = None


class ChatReplyView(StrictModel):
    conversation_id: UUID
    workspace: WorkspaceId
    route_reason: RouteReason
    matched_keywords: list[str]
    answer: str
    citations: list[str]
    escalate: bool

    @classmethod
    def from_model(cls, reply: ChatReply) -> ChatReplyView:
        return cls(**reply.model_dump())


class ChatTurnView(StrictModel):
    role: str
    text: str
    at: datetime

    @classmethod
    def from_model(cls, turn: ChatTurn) -> ChatTurnView:
        return cls(role=turn.role, text=turn.text, at=turn.at)


class ConversationView(StrictModel):
    id: UUID
    workspace: WorkspaceId
    turns: list[ChatTurnView]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, record: ConversationRecord) -> ConversationView:
        return cls(
            id=record.id,
            workspace=record.workspace,
            turns=[ChatTurnView.from_model(turn) for turn in record.turns],
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
