"""Audit domain models — tamper-evident, hash-chained decision records."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models.common import StrictModel, UtcDateTime, payload_digest, utc_now


class ActorType(StrEnum):
    SYSTEM = "system"
    AGENT = "agent"
    HUMAN = "human"


class AuditActor(StrictModel):
    actor_type: ActorType
    actor_id: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)


class AuditEntry(StrictModel):
    """One immutable record in the append-only audit chain.

    ``entry_hash`` covers the full entry content plus ``prev_hash``, forming a
    hash chain: altering any historical entry invalidates every later hash.
    """

    seq: int = Field(ge=0)
    entry_id: UUID = Field(default_factory=uuid4)
    created_at: UtcDateTime = Field(default_factory=utc_now)
    actor: AuditActor
    action: str = Field(min_length=1, max_length=200)
    subject_type: str = Field(min_length=1, max_length=100)
    subject_id: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str | None = None
    entry_hash: str = Field(min_length=64, max_length=64)

    @staticmethod
    def compute_hash(
        *,
        prev_hash: str | None,
        actor: AuditActor,
        action: str,
        subject_type: str,
        subject_id: str,
        payload: dict[str, Any],
        created_at: UtcDateTime,
    ) -> str:
        """Deterministically compute the entry hash for the given content."""
        material: dict[str, Any] = {
            "prev_hash": prev_hash,
            "actor": actor.model_dump(mode="json"),
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload": payload,
            "created_at": created_at.isoformat(),
        }
        return payload_digest(material)

    @classmethod
    def partial(
        cls,
        *,
        seq: int,
        actor: AuditActor,
        action: str,
        subject_type: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
        prev_hash: str | None = None,
        created_at: UtcDateTime | None = None,
    ) -> AuditEntry:
        """Build an entry with its hash computed from the provided content."""
        resolved_payload = payload or {}
        resolved_created = created_at or utc_now()
        digest = cls.compute_hash(
            prev_hash=prev_hash,
            actor=actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=resolved_payload,
            created_at=resolved_created,
        )
        return cls(
            seq=seq,
            created_at=resolved_created,
            actor=actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=resolved_payload,
            prev_hash=prev_hash,
            entry_hash=digest,
        )

    def verify(self) -> bool:
        """Return True if this entry's hash matches its content."""
        expected = self.compute_hash(
            prev_hash=self.prev_hash,
            actor=self.actor,
            action=self.action,
            subject_type=self.subject_type,
            subject_id=self.subject_id,
            payload=self.payload,
            created_at=self.created_at,
        )
        return expected == self.entry_hash
