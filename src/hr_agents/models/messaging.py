"""Messaging domain models — async candidate screening conversations."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models.candidate import Channel
from hr_agents.models.common import StrictModel, UtcDateTime, utc_now


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class ConversationState(StrEnum):
    AWAITING_CONSENT = "awaiting_consent"
    COLLECTING_AVAILABILITY = "collecting_availability"
    CLARIFYING_PROFILE = "clarifying_profile"
    COMPLETE = "complete"
    HANDED_OFF_TO_HUMAN = "handed_off_to_human"


class ScreeningMessage(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    channel: Channel
    direction: MessageDirection
    body: str = Field(min_length=1, max_length=8000)
    status: MessageStatus = MessageStatus.QUEUED
    provider_message_id: str | None = None
    created_at: UtcDateTime = Field(default_factory=utc_now)
    sent_at: UtcDateTime | None = None


class Conversation(StrictModel):
    """A single screening thread with a candidate on one channel."""

    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    channel: Channel
    state: ConversationState = ConversationState.AWAITING_CONSENT
    messages: list[ScreeningMessage] = Field(default_factory=list)
    response_sla_deadline: UtcDateTime | None = None
    created_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)


class ScreeningAction(StrEnum):
    """Side effects a screening turn performed (recorded, never implied)."""

    CONSENT_CAPTURED = "consent_captured"
    AVAILABILITY_RECORDED = "availability_recorded"
    CLARIFICATION_SENT = "clarification_sent"
    INFO_PROVIDED = "info_provided"
    ESCALATED = "escalated"


class ScreeningReply(StrictModel):
    """One validated outbound turn from the ScreeningCoordinator.

    Deterministic validators in the agent module check tone, promises, and state
    transitions before anything is sent; the messaging bridge owns sending.
    """

    message: str = Field(min_length=1, max_length=2000)
    next_state: ConversationState
    actions: list[ScreeningAction] = Field(default_factory=list)
    needs_human: bool = False
    rationale: str = Field(default="", max_length=500)
