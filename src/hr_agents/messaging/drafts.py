"""Email application drafts — CVs that arrived before any consent.

A draft is not an application: it has no candidate record, no queue entry, and
no evaluation. It becomes one only when a named human confirms it with explicit
consent and a job. Until then it sits in this store, deduplicated by provider
message, waiting for a decision or a discard with a reason.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from hr_agents.models import StrictModel, UtcDateTime, payload_digest, utc_now


class EmailDraftStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISCARDED = "discarded"


class EmailApplicationDraft(StrictModel):
    """One unconfirmed inbound application with its stored documents."""

    id: UUID = Field(default_factory=uuid4)
    provider: str = Field(min_length=1, max_length=64)
    provider_message_id: str | None = Field(default=None, max_length=500)
    dedup_key: str = Field(min_length=32, max_length=64)
    sender: str = Field(min_length=1, max_length=320)
    sender_name: str = Field(default="", max_length=320)
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    attachment_names: list[str] = Field(default_factory=list)
    document_ids: list[UUID] = Field(default_factory=list)
    refused_attachments: list[str] = Field(default_factory=list)
    suggested_job_id: UUID | None = None
    status: EmailDraftStatus = EmailDraftStatus.PENDING
    application_id: UUID | None = None
    decided_by: str | None = Field(default=None, max_length=200)
    discard_reason: str | None = Field(default=None, max_length=1000)
    received_at: UtcDateTime = Field(default_factory=utc_now)
    updated_at: UtcDateTime = Field(default_factory=utc_now)


def draft_dedup_key(
    *,
    provider: str,
    message_id: str | None,
    sender: str,
    subject: str,
    body: str,
    file_hashes: list[str],
) -> str:
    """Stable digest of one inbound application mail, including its files."""
    return payload_digest(
        {
            "provider": provider,
            "message_id": (message_id or "").strip().casefold(),
            "sender": sender.strip().casefold(),
            "subject": subject.strip(),
            "body": body.strip(),
            "files": sorted(file_hashes),
        }
    )


class EmailDraftStore:
    """Pending email drafts with exactly-once semantics per provider message."""

    def __init__(self) -> None:
        self._by_id: dict[UUID, EmailApplicationDraft] = {}
        self._by_dedup: dict[tuple[str, str], UUID] = {}

    # persistence primitives (overridden by database adapters)

    def _load(self, draft_id: UUID) -> EmailApplicationDraft | None:
        return self._by_id.get(draft_id)

    def _iter(self) -> Iterator[EmailApplicationDraft]:
        return iter(self._by_id.values())

    def _persist(self, draft: EmailApplicationDraft) -> None:
        self._by_id[draft.id] = draft
        self._by_dedup[(draft.provider, draft.dedup_key)] = draft.id

    # operations

    def find(self, *, provider: str, dedup_key: str) -> EmailApplicationDraft | None:
        """The already-captured draft for a provider/digest pair, if any."""
        draft_id = self._by_dedup.get((provider, dedup_key))
        return None if draft_id is None else self._load(draft_id)

    def add(self, draft: EmailApplicationDraft) -> EmailApplicationDraft:
        """Store a draft; replaying the same provider message is a no-op."""
        existing = self.find(provider=draft.provider, dedup_key=draft.dedup_key)
        if existing is not None:
            return existing
        self._persist(draft)
        return draft

    def get(self, draft_id: UUID) -> EmailApplicationDraft | None:
        return self._load(draft_id)

    def save(self, draft: EmailApplicationDraft) -> None:
        """Persist mutations made to a previously stored draft."""
        if draft.id not in self._by_id:
            raise KeyError(f"unknown email draft {draft.id}")
        self._persist(draft)

    def list_pending(self) -> list[EmailApplicationDraft]:
        """Undecided drafts, oldest first — the human queue."""
        return sorted(
            (draft for draft in self._iter() if draft.status is EmailDraftStatus.PENDING),
            key=lambda draft: draft.received_at,
        )

    def page(
        self, *, status: EmailDraftStatus | None, limit: int, offset: int
    ) -> tuple[list[EmailApplicationDraft], int]:
        """One draft page: ``(received_at, id)`` with an optional status filter."""
        matched = [draft for draft in self._iter() if status is None or draft.status is status]
        matched.sort(key=lambda draft: (draft.received_at, str(draft.id)))
        return matched[offset : offset + limit], len(matched)
