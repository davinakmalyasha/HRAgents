"""Outbox dispatcher — carry queued, human-approved messages over a transport.

The approval already happened at queue time behind a named human; this bridge
only moves bytes. It never composes or edits a body, never touches a message
that is not ``queued``, and records the provider evidence (message id, attempt
count, last error) on the communication and in the audit chain. A failed send
leaves the message queued so the next run — or a human — can retry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import Field, ValidationError

from hr_agents.messaging.base import EmailSender, OutboundEmail, TransportError
from hr_agents.messaging.contacts import CandidateDirectory
from hr_agents.models import (
    Channel,
    CommunicationKind,
    StrictModel,
    UtcDateTime,
    utc_now,
)

if TYPE_CHECKING:
    from hr_agents.services.recruiting import CommunicationService

DEFAULT_DISPATCH_LIMIT = 50

_DEFAULT_SUBJECTS: dict[tuple[CommunicationKind, str], str] = {
    (CommunicationKind.REJECTION, "en"): "Your application update",
    (CommunicationKind.REJECTION, "id"): "Pembaruan lamaran Anda",
    (CommunicationKind.OFFER, "en"): "Your offer",
    (CommunicationKind.OFFER, "id"): "Penawaran Anda",
}


class DispatchOutcome(StrictModel):
    """What happened to one queued message in this run."""

    communication_id: UUID
    ok: bool
    detail: str = ""


class DispatchReport(StrictModel):
    """Counts for one dispatch pass; ``failed`` messages stay queued."""

    started_at: UtcDateTime
    provider: str
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    outcomes: list[DispatchOutcome] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


class DispatchPreview(StrictModel):
    """What a dispatch pass would carry, without sending anything."""

    queued: int
    ready: int
    missing_recipient: int


def default_subject(kind: CommunicationKind, language: str) -> str:
    """Neutral fallback subject; the queued body is never rewritten."""
    return _DEFAULT_SUBJECTS.get((kind, language), "Update on your application")


class OutboxDispatcher:
    """Send queued email messages through the configured transport."""

    def __init__(
        self,
        *,
        communications: CommunicationService,
        sender: EmailSender,
        directory: CandidateDirectory | None = None,
    ) -> None:
        self._communications = communications
        self._sender = sender
        self._directory = directory

    @property
    def provider_id(self) -> str:
        return self._sender.provider_id

    def preview(self, *, limit: int = DEFAULT_DISPATCH_LIMIT) -> DispatchPreview:
        """Count what is ready to send and what has no address on file."""
        queued = self._communications.list_queued(channel=Channel.EMAIL)[: max(limit, 0)]
        ready = sum(1 for item in queued if self._recipient(item.candidate_id, item.recipient))
        return DispatchPreview(
            queued=len(queued),
            ready=ready,
            missing_recipient=len(queued) - ready,
        )

    def dispatch_pending(
        self,
        *,
        limit: int = DEFAULT_DISPATCH_LIMIT,
        started_at: UtcDateTime | None = None,
    ) -> DispatchReport:
        """Send up to ``limit`` queued messages; one failure never stops the rest."""
        report = DispatchReport(
            started_at=started_at or utc_now(),
            provider=self._sender.provider_id,
        )
        for item in self._communications.list_queued(channel=Channel.EMAIL)[: max(limit, 0)]:
            self._dispatch_one(item.id, report)
        return report

    # internals

    def _dispatch_one(self, communication_id: UUID, report: DispatchReport) -> None:
        item = self._communications.get(communication_id)
        recipient = self._recipient(item.candidate_id, item.recipient)
        if recipient is None:
            report.skipped += 1
            report.outcomes.append(
                DispatchOutcome(
                    communication_id=communication_id,
                    ok=False,
                    detail="no candidate email address on file",
                )
            )
            return
        try:
            message = OutboundEmail(
                to=recipient,
                subject=item.subject or default_subject(item.kind, item.language),
                body=item.body,
            )
            result = self._sender.send(message)
        except (TransportError, ValidationError) as exc:
            self._communications.record_dispatch_failure(
                communication_id,
                provider=self._sender.provider_id,
                error=str(exc),
            )
            report.failed += 1
            report.outcomes.append(
                DispatchOutcome(communication_id=communication_id, ok=False, detail=str(exc)[:500])
            )
            return
        if not result.accepted:
            detail = result.detail or "the transport refused the message"
            self._communications.record_dispatch_failure(
                communication_id,
                provider=result.provider,
                error=detail,
            )
            report.failed += 1
            report.outcomes.append(
                DispatchOutcome(communication_id=communication_id, ok=False, detail=detail[:500])
            )
            return
        self._communications.record_dispatch(
            communication_id,
            provider=result.provider,
            recipient=recipient,
            message_id=result.message_id,
        )
        report.sent += 1
        report.outcomes.append(
            DispatchOutcome(
                communication_id=communication_id,
                ok=True,
                detail=f"dispatched via {result.provider}",
            )
        )

    def _recipient(self, candidate_id: UUID, queued_recipient: str | None) -> str | None:
        if queued_recipient:
            return queued_recipient
        if self._directory is None:
            return None
        return self._directory.primary_email(candidate_id)
