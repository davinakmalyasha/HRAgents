"""Request/response schemas for Web Push subscriptions."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from hr_agents.models import PushSubscription, StrictModel, UtcDateTime


class PushConfigView(StrictModel):
    """What the browser needs to subscribe: the public half of the VAPID pair."""

    enabled: bool
    public_key: str | None = Field(
        default=None,
        description=(
            "Base64url application server key. Present only when the operator "
            "configured a VAPID pair; the private half never leaves the server."
        ),
    )


class PushKeys(StrictModel):
    """The browser-generated encryption material for one endpoint."""

    p256dh: str = Field(min_length=16, max_length=500)
    auth: str = Field(min_length=8, max_length=200)


class PushSubscriptionCreate(StrictModel):
    endpoint: str = Field(
        min_length=8,
        max_length=512,
        description="The push service endpoint from PushSubscription.toJSON(); HTTPS only.",
    )
    keys: PushKeys
    user_agent: str | None = Field(default=None, max_length=500)


class PushSubscriptionView(StrictModel):
    """A subscription as the owning person sees it. Keys are never echoed."""

    id: UUID
    endpoint: str
    user_agent: str | None
    created_at: UtcDateTime
    last_seen_at: UtcDateTime

    @classmethod
    def from_model(cls, record: PushSubscription) -> PushSubscriptionView:
        return cls(
            id=record.id,
            endpoint=record.endpoint,
            user_agent=record.user_agent,
            created_at=record.created_at,
            last_seen_at=record.last_seen_at,
        )


class PushTestView(StrictModel):
    """The outcome of one explicit test delivery."""

    attempted: int = Field(ge=0)
    delivered: int = Field(ge=0)
    pruned: int = Field(ge=0)
    failed: int = Field(ge=0)
