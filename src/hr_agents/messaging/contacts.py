"""Candidate contact lookup for the messaging bridge.

The bridge needs two deterministic lookups: the address a queued message goes
to, and the candidate an inbound reply belongs to. Both come from a port so the
outbox never guesses, and an empty directory simply means "no address recorded".
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import EmailStr


@runtime_checkable
class CandidateDirectory(Protocol):
    """Address book the bridge consults before carrying a message."""

    def primary_email(self, candidate_id: UUID) -> str | None:
        """The candidate's recorded email address, when one is on file."""

    def candidate_for_email(self, address: str) -> UUID | None:
        """The candidate owning an address, matched case-insensitively."""


class InMemoryCandidateDirectory:
    """Explicit address book; nothing is inferred from names or documents."""

    def __init__(self) -> None:
        self._by_candidate: dict[UUID, str] = {}

    def add(self, candidate_id: UUID, email: EmailStr | str) -> None:
        """Record (or replace) the address used for a candidate."""
        self._by_candidate[candidate_id] = str(email)

    def primary_email(self, candidate_id: UUID) -> str | None:
        return self._by_candidate.get(candidate_id)

    def candidate_for_email(self, address: str) -> UUID | None:
        target = address.strip().casefold()
        for candidate_id, email in self._by_candidate.items():
            if email.strip().casefold() == target:
                return candidate_id
        return None
