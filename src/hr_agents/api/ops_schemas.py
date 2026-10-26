"""Schemas for the operator endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from hr_agents.models import McpServerStatus, StrictModel, UtcDateTime
from hr_agents.models.mcp import McpImpact
from hr_agents.providers.queue import QueueMessage


class DeadLetterView(StrictModel):
    """One dead-lettered message, with metadata but not the payload itself.

    The payload of an evaluation message carries a résumé. An operator needs to
    know what failed and where, not to read candidate data from an ops screen;
    the keys are listed so the message type is identifiable without exposing a
    single value.
    """

    message_id: str
    topic: str
    created_at: UtcDateTime
    attempts: int = Field(ge=0)
    failed_reason: str | None = None
    failed_at: UtcDateTime | None = None
    payload_keys: list[str]
    application_id: UUID | None = None

    @classmethod
    def from_message(cls, message: QueueMessage) -> DeadLetterView:
        application_id: UUID | None = None
        raw = message.payload.get("application_id")
        if isinstance(raw, str):
            try:
                application_id = UUID(raw)
            except ValueError:
                application_id = None
        return cls(
            message_id=message.id,
            topic=message.topic,
            created_at=message.created_at,
            attempts=message.attempts,
            failed_reason=message.failed_reason,
            failed_at=message.failed_at,
            payload_keys=sorted(message.payload),
            application_id=application_id,
        )


class DeadLetterRequeue(StrictModel):
    reason: str = Field(min_length=1, max_length=1000)


class DeadLetterRequeueResult(StrictModel):
    requeued: bool


class McpServerView(StrictModel):
    """One connection, from the environment or the dashboard, with live status."""

    name: str
    url: str
    source: str
    auth_env: str | None = None
    timeout_seconds: float
    allowed_agents: list[str] = Field(default_factory=list)
    tools: dict[str, McpImpact] = Field(default_factory=dict)
    status: McpServerStatus | None = None
