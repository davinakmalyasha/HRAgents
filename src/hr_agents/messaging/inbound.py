"""Inbound reply ingestion — record what candidates wrote back, decide nothing.

A polled message is attributed the deterministic way: the outbound message id
it answers (``In-Reply-To``/``References``) first, then the sender's address
against the candidate directory. Anything that matches neither is counted and
left alone — the bridge never guesses who a message belongs to, and a reply
never changes an offer, a stage, or a decision on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import Field

from hr_agents.messaging.base import InboundEmail
from hr_agents.messaging.contacts import CandidateDirectory
from hr_agents.messaging.store import ReplyStore, reply_dedup_key
from hr_agents.models import (
    ActorType,
    AuditActor,
    CandidateCommunication,
    CandidateReply,
    StrictModel,
    UtcDateTime,
    utc_now,
)
from hr_agents.services.audit import AuditChain

if TYPE_CHECKING:
    from hr_agents.services.recruiting import CommunicationService


class IngestOutcome(StrictModel):
    """What happened to one polled message."""

    from_address: str
    matched: bool
    candidate_id: UUID | None = None
    reply_id: UUID | None = None
    detail: str = ""


class IngestReport(StrictModel):
    """Counts for one polling pass; unmatched mail is never stored."""

    started_at: UtcDateTime
    provider: str
    matched: int = 0
    unmatched: int = 0
    duplicates: int = 0
    outcomes: list[IngestOutcome] = Field(default_factory=list)


class ReplyIngestor:
    """Attribute polled mail to candidates and store it as evidence."""

    def __init__(
        self,
        *,
        replies: ReplyStore,
        communications: CommunicationService,
        directory: CandidateDirectory | None = None,
        audit: AuditChain | None = None,
    ) -> None:
        self._replies = replies
        self._communications = communications
        self._directory = directory
        self._audit = audit or AuditChain()

    def ingest(
        self,
        messages: Sequence[InboundEmail],
        *,
        started_at: UtcDateTime | None = None,
    ) -> IngestReport:
        """Store every attributable reply once; count the rest without writing."""
        report = IngestReport(
            started_at=started_at or utc_now(),
            provider=messages[0].provider if messages else "none",
        )
        for message in messages:
            self._ingest_one(message, report)
        return report

    # internals

    def _ingest_one(self, message: InboundEmail, report: IngestReport) -> None:
        candidate_id = self._attribute(message)
        if candidate_id is None:
            report.unmatched += 1
            report.outcomes.append(
                IngestOutcome(
                    from_address=message.from_address,
                    matched=False,
                    detail="no candidate matches this sender",
                )
            )
            return
        dedup_key = reply_dedup_key(
            provider=message.provider,
            message_id=message.message_id,
            sender=message.from_address,
            subject=message.subject,
            body=message.body,
        )
        existing = self._replies.find(provider=message.provider, dedup_key=dedup_key)
        if existing is not None:
            report.duplicates += 1
            report.outcomes.append(
                IngestOutcome(
                    from_address=message.from_address,
                    matched=True,
                    candidate_id=candidate_id,
                    reply_id=existing.id,
                    detail="already captured",
                )
            )
            return
        communication = self._thread(message)
        reply = self._replies.add(
            CandidateReply(
                candidate_id=candidate_id,
                communication_id=communication.id if communication else None,
                sender=message.from_address,
                subject=message.subject,
                body=message.body,
                provider=message.provider,
                provider_message_id=message.message_id,
                dedup_key=dedup_key,
                received_at=message.received_at,
            )
        )
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.SYSTEM, actor_id=f"transport:{message.provider}"),
            action="communication.reply_received",
            subject_type="candidate_reply",
            subject_id=str(reply.id),
            payload={
                "candidate_id": str(candidate_id),
                "communication_id": str(communication.id) if communication else None,
                "provider": message.provider,
                "message_id": message.message_id,
            },
        )
        report.matched += 1
        report.outcomes.append(
            IngestOutcome(
                from_address=message.from_address,
                matched=True,
                candidate_id=candidate_id,
                reply_id=reply.id,
                detail="stored",
            )
        )

    def _attribute(self, message: InboundEmail) -> UUID | None:
        communication = self._thread(message)
        if communication is not None:
            return communication.candidate_id
        if self._directory is None:
            return None
        return self._directory.candidate_for_email(message.from_address)

    def _thread(self, message: InboundEmail) -> CandidateCommunication | None:
        """The dispatched message this reply answers, when the headers say so."""
        for reference in (message.in_reply_to, *message.references):
            if not reference:
                continue
            communication = self._communications.find_by_provider_message_id(reference)
            if communication is not None:
                return communication
        return None
