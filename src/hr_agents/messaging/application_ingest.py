"""Email application ingestion — CVs that arrive in the hiring mailbox.

A message the reply bridge cannot attribute, carrying document attachments, is
an application waiting for consent — not a reply. It becomes a draft: stored
documents, a job suggestion when the subject names one exactly, and no
candidate record, no queue entry, no evaluation. A named human confirms it
with explicit consent, or discards it with a reason. Anything without a usable
attachment is left alone; the bridge never guesses.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import Field

from hr_agents.identity import ActorRef
from hr_agents.messaging.base import InboundEmail
from hr_agents.messaging.contacts import CandidateDirectory
from hr_agents.messaging.drafts import (
    EmailApplicationDraft,
    EmailDraftStore,
    draft_dedup_key,
)
from hr_agents.models import StrictModel, UtcDateTime, utc_now
from hr_agents.services.audit import AuditChain

if TYPE_CHECKING:
    from hr_agents.services.recruiting import CommunicationService, DocumentService, JobService

_SUBJECT_PREFIXES = (
    "re:",
    "fwd:",
    "fw:",
    "lamaran",
    "lamaran kerja",
    "application for",
    "application:",
    "applying for",
    "aplikasi untuk",
    "posisi",
    "posisi:",
    "position",
    "position:",
)


def normalize_subject(subject: str) -> str:
    """The subject with reply prefixes and application boilerplate removed."""
    text = " ".join(subject.strip().casefold().split())
    changed = True
    while changed:
        changed = False
        for prefix in _SUBJECT_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].strip(" :-.")
                changed = True
    return text


def suggest_job(subject: str, titles: dict[str, UUID]) -> UUID | None:
    """The job whose title the subject names exactly, or nothing.

    Equality only: a subject that merely resembles a title is a human's call,
    and the draft stays unassigned rather than filing into the wrong req.
    """
    wanted = normalize_subject(subject)
    return titles.get(wanted) if wanted else None


class ApplicationIngestOutcome(StrictModel):
    """What happened to one polled message."""

    from_address: str
    drafted: bool = False
    draft_id: UUID | None = None
    detail: str = ""


class ApplicationIngestReport(StrictModel):
    """Counts for one application-ingest pass; nothing here evaluates."""

    started_at: UtcDateTime
    provider: str
    polled: int = 0
    drafted: int = 0
    duplicates: int = 0
    skipped_is_reply: int = 0
    skipped_no_attachments: int = 0
    outcomes: list[ApplicationIngestOutcome] = Field(default_factory=list)


class ApplicationIngestor:
    """Turn unattributed mail with CV attachments into consent-pending drafts."""

    def __init__(
        self,
        *,
        drafts: EmailDraftStore,
        documents: DocumentService,
        jobs: JobService,
        communications: CommunicationService,
        directory: CandidateDirectory | None = None,
        audit: AuditChain | None = None,
    ) -> None:
        self._drafts = drafts
        self._documents = documents
        self._jobs = jobs
        self._communications = communications
        self._directory = directory
        self._audit = audit or AuditChain()

    def ingest(
        self,
        messages: Sequence[InboundEmail],
        *,
        started_at: UtcDateTime | None = None,
    ) -> ApplicationIngestReport:
        """Draft every unattributed message with attachments; count the rest."""
        from hr_agents.models import JobStatus

        report = ApplicationIngestReport(
            started_at=started_at or utc_now(),
            provider=messages[0].provider if messages else "none",
        )
        titles = {
            " ".join(job.title.strip().casefold().split()): job.id
            for job in self._jobs.list_all(status=JobStatus.OPEN)
        }
        for message in messages:
            report.polled += 1
            self._ingest_one(message, titles, report)
        return report

    # internals

    def _ingest_one(
        self,
        message: InboundEmail,
        titles: dict[str, UUID],
        report: ApplicationIngestReport,
    ) -> None:
        if self._is_reply(message):
            report.skipped_is_reply += 1
            report.outcomes.append(
                ApplicationIngestOutcome(
                    from_address=message.from_address,
                    detail="answers a dispatched message; the reply bridge owns it",
                )
            )
            return
        if not message.attachments:
            report.skipped_no_attachments += 1
            report.outcomes.append(
                ApplicationIngestOutcome(
                    from_address=message.from_address,
                    detail="no document attachments; not an application",
                )
            )
            return
        file_hashes = [hashlib.sha256(item.content).hexdigest() for item in message.attachments]
        key = draft_dedup_key(
            provider=message.provider,
            message_id=message.message_id,
            sender=message.from_address,
            subject=message.subject,
            body=message.body,
            file_hashes=file_hashes,
        )
        existing = self._drafts.find(provider=message.provider, dedup_key=key)
        if existing is not None:
            report.duplicates += 1
            report.outcomes.append(
                ApplicationIngestOutcome(
                    from_address=message.from_address,
                    draft_id=existing.id,
                    detail="already drafted",
                )
            )
            return
        document_ids: list[UUID] = []
        names: list[str] = []
        refused: list[str] = list(message.skipped_attachments)
        from hr_agents.services.recruiting import RecruitingError

        for index, attachment in enumerate(message.attachments):
            try:
                stored = self._documents.upload(
                    filename=attachment.filename,
                    kind="cv" if index == 0 else "other",
                    content=attachment.content,
                    actor=ActorRef.system("mail-ingest"),
                )
            except RecruitingError as exc:
                refused.append(f"{attachment.filename}: {exc}")
                continue
            document_ids.append(stored.id)
            names.append(attachment.filename)
        draft = self._drafts.add(
            EmailApplicationDraft(
                provider=message.provider,
                provider_message_id=message.message_id,
                dedup_key=key,
                sender=str(message.from_address),
                sender_name=message.from_name,
                subject=message.subject,
                body=message.body,
                attachment_names=names,
                document_ids=document_ids,
                refused_attachments=refused,
                suggested_job_id=suggest_job(message.subject, titles),
            )
        )
        self._audit.append(
            actor=ActorRef.system(f"transport:{message.provider}").audit_actor(),
            action="application.draft_received",
            subject_type="email_application_draft",
            subject_id=str(draft.id),
            payload={
                "sender": str(message.from_address),
                "documents": len(document_ids),
                "refused": len(refused),
                "suggested_job_id": (
                    str(draft.suggested_job_id) if draft.suggested_job_id else None
                ),
            },
        )
        report.drafted += 1
        report.outcomes.append(
            ApplicationIngestOutcome(
                from_address=message.from_address,
                drafted=True,
                draft_id=draft.id,
                detail=f"{len(document_ids)} document(s) stored, awaiting consent",
            )
        )

    def _is_reply(self, message: InboundEmail) -> bool:
        """Whether the reply bridge already owns this message as a thread answer."""
        for reference in (message.in_reply_to, *message.references):
            if not reference:
                continue
            if self._communications.find_by_provider_message_id(reference) is not None:
                return True
        return False
