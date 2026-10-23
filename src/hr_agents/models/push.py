"""Web Push subscriptions.

A subscription is a browser endpoint plus the keys the browser generated for it.
The server stores them; the browser's push service does the delivery. A
notification carries a pointer ("an approval is waiting"), never employee data:
a lock screen is not an access-controlled surface.

``role`` is a snapshot of the subscribing principal's role, used to decide who
receives an approval ping. It is a cache, not an authority -- the sending side
re-resolves the identity against the configured principals, so a revoked key
stops receiving notifications even though its subscription row remains.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models.common import UtcDateTime, Versioned, utc_now


class PushSubscription(Versioned):
    """One browser's push endpoint and its encryption material."""

    id: UUID = Field(default_factory=uuid4)
    actor_id: str = Field(min_length=1, max_length=200)
    role: str = Field(
        min_length=1,
        max_length=32,
        description=(
            "The principal role at subscription time. Approval pings select on it; "
            "the sender re-checks the live role before delivering."
        ),
    )
    endpoint: str = Field(min_length=8, max_length=512)
    p256dh: str = Field(min_length=16, max_length=500)
    auth: str = Field(min_length=8, max_length=200)
    user_agent: str | None = Field(default=None, max_length=500)
    created_at: UtcDateTime = Field(default_factory=utc_now)
    last_seen_at: UtcDateTime = Field(default_factory=utc_now)
