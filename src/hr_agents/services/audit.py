"""Hash-chained audit log.

Every entry's ``entry_hash`` covers its content plus the previous entry's hash.
Altering any historical entry invalidates every later hash — tamper evidence
without cryptography infrastructure.
"""

from __future__ import annotations

from typing import Any

from hr_agents.models import ActorType, AuditActor, AuditEntry


class AuditChainError(RuntimeError):
    """Raised when a chain write would break integrity."""


class AuditChain:
    """Append-only in-memory hash chain.

    A persistent sink (Postgres) attaches in a later phase; this class owns the
    chaining semantics so both share identical behavior.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    @property
    def last_hash(self) -> str | None:
        return self._entries[-1].entry_hash if self._entries else None

    def append(
        self,
        *,
        actor: AuditActor,
        action: str,
        subject_type: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Append a new entry, linking it to the previous hash."""
        seq = len(self._entries)
        prev_hash = self.last_hash
        entry = AuditEntry.partial(
            seq=seq,
            actor=actor,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload or {},
            prev_hash=prev_hash,
        )
        self._entries.append(entry)
        return entry

    def append_system(
        self,
        *,
        action: str,
        subject_type: str,
        subject_id: str,
        payload: dict[str, Any] | None = None,
        actor_id: str = "system",
    ) -> AuditEntry:
        return self.append(
            actor=AuditActor(actor_type=ActorType.SYSTEM, actor_id=actor_id),
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )

    def verify(self) -> int:
        """Verify the full chain.

        Returns ``-1`` when the chain is intact, otherwise the ``seq`` of the
        first invalid entry.
        """
        expected_prev: str | None = None
        for entry in self._entries:
            if entry.prev_hash != expected_prev:
                return entry.seq
            if not entry.verify():
                return entry.seq
            expected_prev = entry.entry_hash
        return -1
