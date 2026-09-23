"""Inbound candidate reply store.

Replies are evidence, not decisions: they are stored verbatim with the provider
message id, correlated to the message they answer, and deduplicated so repeated
polls of the same mailbox never double-count. Database adapters override the
``_load``/``_iter``/``_persist`` primitives.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from hr_agents.models import CandidateReply, payload_digest


def reply_dedup_key(
    *,
    provider: str,
    message_id: str | None,
    sender: str,
    subject: str,
    body: str,
) -> str:
    """Stable digest of one inbound message, used to skip repeat polls."""
    return payload_digest(
        {
            "provider": provider,
            "message_id": (message_id or "").strip().casefold(),
            "sender": sender.strip().casefold(),
            "subject": subject.strip(),
            "body": body.strip(),
        }
    )


class ReplyStore:
    """Candidate replies keyed by UUID, deduplicated per provider message."""

    def __init__(self) -> None:
        self._items: dict[UUID, CandidateReply] = {}
        self._by_dedup: dict[tuple[str, str], UUID] = {}

    # persistence primitives (overridden by database adapters)

    def _load(self, reply_id: UUID) -> CandidateReply | None:
        return self._items.get(reply_id)

    def _iter(self) -> Iterator[CandidateReply]:
        return iter(self._items.values())

    def _persist(self, reply: CandidateReply) -> None:
        self._items[reply.id] = reply
        self._by_dedup[(reply.provider, reply.dedup_key)] = reply.id

    # operations

    def find(self, *, provider: str, dedup_key: str) -> CandidateReply | None:
        """The already-stored reply for a provider/digest pair, if any."""
        reply_id = self._by_dedup.get((provider, dedup_key))
        return None if reply_id is None else self._load(reply_id)

    def add(self, reply: CandidateReply) -> CandidateReply:
        """Store a reply; replaying the same provider message is a no-op."""
        existing = self.find(provider=reply.provider, dedup_key=reply.dedup_key)
        if existing is not None:
            return existing
        self._persist(reply)
        return reply

    def get(self, reply_id: UUID) -> CandidateReply | None:
        return self._load(reply_id)

    def list_for(self, candidate_id: UUID) -> list[CandidateReply]:
        return sorted(
            (reply for reply in self._iter() if reply.candidate_id == candidate_id),
            key=lambda reply: reply.received_at,
        )

    def list_all(self) -> list[CandidateReply]:
        return list(self._iter())
