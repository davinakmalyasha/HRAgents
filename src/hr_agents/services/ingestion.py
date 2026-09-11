"""Ingestion service: application store, idempotency, and job queue.

The in-memory implementations here define the behavioral contract; Redis and
PostgreSQL adapters arrive in the integrations phase and must satisfy it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from hr_agents.models import (
    ConsentRecord,
    Recommendation,
    payload_digest,
)
from hr_agents.services.priority import PriorityInputs, compute_priority


class ApplicationStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    EVALUATED = "evaluated"
    GATED = "gated"
    SCHEDULED = "scheduled"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


@dataclass
class SubmissionInput:
    """Normalized application submission (API models convert into this)."""

    job_id: UUID
    source_channel: str
    consent_granted: bool
    consent_policy_version: str = "1.0"
    candidate_name: str = ""
    candidate_emails: list[str] = field(default_factory=list)
    candidate_links: dict[str, Any] = field(default_factory=dict)
    document_ids: list[UUID] = field(default_factory=list)
    questionnaire: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def payload_hash(self) -> str:
        return payload_digest(
            {
                "job_id": str(self.job_id),
                "source_channel": self.source_channel,
                "consent_granted": self.consent_granted,
                "candidate_name": self.candidate_name,
                "candidate_emails": sorted(self.candidate_emails),
                "candidate_links": self.candidate_links,
                "document_ids": sorted(str(doc) for doc in self.document_ids),
                "questionnaire": self.questionnaire,
                "metadata": self.metadata,
            }
        )


@dataclass
class ApplicationRecord:
    id: UUID
    candidate_id: UUID
    job_id: UUID
    source_channel: str
    status: ApplicationStatus
    received_at: datetime
    consent: ConsentRecord
    idempotency_key: str | None = None
    s_tech: float | None = None
    sigma: float | None = None
    recommendation: Recommendation | None = None
    priority_score: float = 0.0
    timeline: list[tuple[datetime, str]] = field(default_factory=list)

    def note(self, event: str) -> None:
        self.timeline.append((datetime.now(UTC), event))

    def refresh_priority(self, *, risk_flag_count: int = 0) -> None:
        hours = (datetime.now(UTC) - self.received_at).total_seconds() / 3600.0
        self.priority_score = compute_priority(
            PriorityInputs(
                s_tech=self.s_tech if self.s_tech is not None else 0.0,
                hours_waiting=hours,
                availability_completeness=0.0,
                risk_flag_count=risk_flag_count,
            )
        )


class SubmissionConflictError(RuntimeError):
    """Same idempotency key was reused with a different payload."""


class ApplicationStore:
    """In-memory application store with exactly-once idempotency semantics."""

    def __init__(self) -> None:
        self._by_id: dict[UUID, ApplicationRecord] = {}
        self._idempotency: dict[str, tuple[str, UUID]] = {}

    def submit(
        self,
        submission: SubmissionInput,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[ApplicationRecord, bool]:
        """Register a submission.

        Returns ``(record, created)`` where ``created`` is False for idempotent
        replays. Raises ``SubmissionConflictError`` when a key is reused with a
        different payload.
        """
        payload_hash = submission.payload_hash()

        if idempotency_key is not None and idempotency_key in self._idempotency:
            stored_hash, application_id = self._idempotency[idempotency_key]
            if stored_hash != payload_hash:
                raise SubmissionConflictError(
                    "idempotency key already used with a different payload"
                )
            return self._by_id[application_id], False

        record = ApplicationRecord(
            id=uuid4(),
            candidate_id=uuid4(),
            job_id=submission.job_id,
            source_channel=submission.source_channel,
            status=ApplicationStatus.QUEUED,
            received_at=datetime.now(UTC),
            consent=ConsentRecord(
                granted=submission.consent_granted,
                granted_at=datetime.now(UTC) if submission.consent_granted else None,
                policy_version=submission.consent_policy_version,
            ),
            idempotency_key=idempotency_key,
        )
        record.note("application.received")
        record.refresh_priority()

        self._by_id[record.id] = record
        if idempotency_key is not None:
            self._idempotency[idempotency_key] = (payload_hash, record.id)
        return record, True

    def get(self, application_id: UUID) -> ApplicationRecord | None:
        return self._by_id.get(application_id)

    def find_by_candidate(self, candidate_id: UUID) -> list[ApplicationRecord]:
        return [r for r in self._by_id.values() if r.candidate_id == candidate_id]

    def set_status(
        self, application_id: UUID, status: ApplicationStatus, *, event: str
    ) -> ApplicationRecord | None:
        """Update status and append a timeline note; None when unknown."""
        record = self._by_id.get(application_id)
        if record is None:
            return None
        record.status = status
        record.note(event)
        return record

    def list_for_job(self, job_id: UUID) -> list[ApplicationRecord]:
        records = [r for r in self._by_id.values() if r.job_id == job_id]
        records.sort(key=lambda r: (-r.priority_score, r.received_at))
        return records

    def iter_all(self) -> Iterator[ApplicationRecord]:
        return iter(self._by_id.values())


class JobQueue:
    """Minimal in-process work queue contract (Redis Streams adapter later)."""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []

    def enqueue(self, job_type: str, payload: dict[str, Any]) -> None:
        self._items.append({"type": job_type, "payload": payload})

    def dequeue(self) -> dict[str, Any] | None:
        return self._items.pop(0) if self._items else None

    def __len__(self) -> int:
        return len(self._items)
