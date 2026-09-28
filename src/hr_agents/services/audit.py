"""Hash-chained audit log.

Every entry's ``entry_hash`` covers its content plus the previous entry's hash.
Altering any historical entry invalidates every later hash — tamper evidence
without cryptography infrastructure.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from hr_agents.models import ActorType, AuditActor, AuditEntry


class AuditChainError(RuntimeError):
    """Raised when a chain write would break integrity."""


@dataclass(frozen=True)
class ChainCursor:
    """Carried state for streaming verification of a long chain."""

    expected_prev: str | None = None
    last_seq: int | None = None


def chain_is_linked(entry: AuditEntry, cursor: ChainCursor) -> bool:
    """Is this entry correctly linked to the one before it, given the cursor?"""
    if entry.prev_hash != cursor.expected_prev:
        return False
    return entry.verify()


def verify_entries(entries: Sequence[AuditEntry]) -> int:
    """Return -1 when the chain is intact, else the first invalid ``seq``."""
    return verify_stream(entries)


def verify_stream(entries: Iterable[AuditEntry]) -> int:
    """Verify a chain of any length without materializing it.

    Streaming matters because the persisted chain grows forever: a verification
    pass that loads every entry turns a routine ops check into an OOM risk.
    """
    cursor = ChainCursor()
    for entry in entries:
        if not chain_is_linked(entry, cursor):
            return entry.seq
        cursor = ChainCursor(expected_prev=entry.entry_hash, last_seq=entry.seq)
    return -1


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
        return verify_entries(self._entries)
