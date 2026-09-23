"""Messaging domain models — async candidate screening conversations."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import EmailStr, Field

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


class CommunicationKind(StrEnum):
    """Consequential candidate messages that follow a hiring decision."""

    REJECTION = "rejection"
    OFFER = "offer"


class CommunicationStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    CANCELLED = "cancelled"


class CandidateCommunication(StrictModel):
    """A candidate-facing message, queued only behind a named human.

    Dispatch is carried by a transport bridge (SMTP/IMAP) or by a human via the
    always-available manual path; either way the queue-time approval is the gate
    and the dispatch evidence (actor, provider, message id) is recorded against
    the message.
    """

    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    application_id: UUID | None = None
    evaluation_id: UUID | None = None
    kind: CommunicationKind
    channel: Channel = Channel.EMAIL
    language: Literal["en", "id"] = "en"
    subject: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    status: CommunicationStatus = CommunicationStatus.QUEUED
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at: UtcDateTime = Field(default_factory=utc_now)
    sent_by: str | None = Field(default=None, max_length=200)
    sent_at: UtcDateTime | None = None
    recipient: EmailStr | None = None
    provider: str | None = Field(default=None, max_length=64)
    provider_message_id: str | None = Field(default=None, max_length=500)
    send_attempts: int = Field(default=0, ge=0)
    last_error: str | None = Field(default=None, max_length=500)
    created_at: UtcDateTime = Field(default_factory=utc_now)


class CandidateReply(StrictModel):
    """An inbound candidate message captured from a connected mailbox.

    Replies are evidence, never decisions: an offer acceptance still requires a
    named human through the offer API.
    """

    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID
    communication_id: UUID | None = None
    channel: Channel = Channel.EMAIL
    sender: EmailStr
    subject: str = Field(default="", max_length=500)
    body: str = Field(min_length=1, max_length=8000)
    provider: str = Field(min_length=1, max_length=64)
    provider_message_id: str | None = Field(default=None, max_length=500)
    dedup_key: str = Field(min_length=32, max_length=64)
    received_at: UtcDateTime = Field(default_factory=utc_now)


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
