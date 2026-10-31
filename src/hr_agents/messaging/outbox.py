"""Outbox dispatcher — carry queued, human-approved messages over a transport.

The approval already happened at queue time behind a named human; this bridge
only moves bytes. It never composes or edits a body, never touches a message
that is not ``queued``, and records the provider evidence (message id, attempt
count, last error) on the communication and in the audit chain. A failed send
leaves the message queued so the next run — or a human — can retry.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import Field

from hr_agents.logging import get_logger
from hr_agents.messaging.base import EmailSender, OutboundEmail
from hr_agents.messaging.contacts import CandidateDirectory
from hr_agents.models import (
    Channel,
    CommunicationKind,
    CommunicationStatus,
    StrictModel,
    UtcDateTime,
    utc_now,
)

if TYPE_CHECKING:
    from hr_agents.services.recruiting import CommunicationService

logger = get_logger(__name__)

DEFAULT_DISPATCH_LIMIT = 50

RETRY_BASE_SECONDS = 15 * 60
RETRY_MAX_SECONDS = 24 * 60 * 60


def retry_delay(attempts: int) -> timedelta:
    """How long to wait after ``attempts`` failed sends: 15 min, 30, 60, … capped at 24 h.

    Without it a bounced address was retried on every scheduler tick forever: the
    same dead mailbox hit every fifteen minutes, and no operator could tell from
    the record whether the next attempt was due. The delay is a cooling-off
    period, not a cap — the message stays queued and keeps being retried, just
    progressively less often, so a fixed mailbox recovers on its own.
    """
    if attempts <= 0:
        return timedelta(0)
    # Clamp the exponent: the result is capped at 24 h long before it matters, and
    # a counter that somehow reached six figures must not build a huge integer first.
    exponent = min(attempts - 1, 16)
    seconds = min(RETRY_BASE_SECONDS * (2**exponent), RETRY_MAX_SECONDS)
    return timedelta(seconds=seconds)


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
    unrecorded: int = 0
    deferred: int = 0
    outcomes: list[DispatchOutcome] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """A pass is clean only when nothing failed *and* nothing is ambiguous.

        ``unrecorded`` is a message the transport accepted whose evidence could
        not be written (a concurrent run recorded it first, or the database
        refused). Counting it as a failure would be a lie about delivery;
        counting it as success would hide a candidate who was written to twice.
        """
        return self.failed == 0 and self.unrecorded == 0


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
        moment = started_at or utc_now()
        report = DispatchReport(
            started_at=moment,
            provider=self._sender.provider_id,
        )
        for item in self._communications.list_queued(channel=Channel.EMAIL)[: max(limit, 0)]:
            self._dispatch_one(item.id, report, now=moment)
        return report

    # internals

    def _dispatch_one(
        self, communication_id: UUID, report: DispatchReport, *, now: datetime
    ) -> None:
        item = self._communications.get(communication_id)
        if item.status is not CommunicationStatus.QUEUED:
            # The list was read before this iteration; a human may have withdrawn
            # or already sent the message in between. Sending it anyway is how a
            # candidate receives a second copy of a rejection.
            report.skipped += 1
            report.outcomes.append(
                DispatchOutcome(
                    communication_id=communication_id,
                    ok=False,
                    detail=f"no longer queued ({item.status.value})",
                )
            )
            return
        if item.send_attempts > 0 and item.last_attempt_at is not None:
            ready_at = item.last_attempt_at + retry_delay(item.send_attempts)
            if now < ready_at:
                report.deferred += 1
                report.outcomes.append(
                    DispatchOutcome(
                        communication_id=communication_id,
                        ok=False,
                        detail=(
                            f"attempt {item.send_attempts} failed; "
                            f"next try after {ready_at.isoformat()}"
                        ),
                    )
                )
                return
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
        except Exception as exc:
            # Any sender, including an operator-supplied adapter, may raise
            # something that is not TransportError. Containing it here keeps the
            # documented promise -- one failure never stops the rest -- instead
            # of letting a single mailbox error abandon the whole batch.
            self._record_failure(
                communication_id, provider=self._sender.provider_id, error=str(exc)
            )
            report.failed += 1
            report.outcomes.append(
                DispatchOutcome(communication_id=communication_id, ok=False, detail=str(exc)[:500])
            )
            return
        if not result.accepted:
            detail = result.detail or "the transport refused the message"
            self._record_failure(communication_id, provider=result.provider, error=detail)
            report.failed += 1
            report.outcomes.append(
                DispatchOutcome(communication_id=communication_id, ok=False, detail=detail[:500])
            )
            return
        try:
            self._communications.record_dispatch(
                communication_id,
                provider=result.provider,
                recipient=recipient,
                message_id=result.message_id,
            )
        except Exception as exc:
            # The bytes left the building but the evidence did not land: usually
            # another run recorded it first. Retrying would send a second copy,
            # so this is reported as ambiguous, not as a failure to send.
            logger.error(
                "messaging.dispatch_record_failed",
                communication_id=str(communication_id),
                provider=result.provider,
                error=type(exc).__name__,
            )
            report.unrecorded += 1
            report.outcomes.append(
                DispatchOutcome(
                    communication_id=communication_id,
                    ok=False,
                    detail=(
                        "sent by the transport, but the record could not be updated "
                        f"({type(exc).__name__}: {exc}); do not retry blindly"
                    )[:500],
                )
            )
            return
        report.sent += 1
        report.outcomes.append(
            DispatchOutcome(
                communication_id=communication_id,
                ok=True,
                detail=f"dispatched via {result.provider}",
            )
        )

    def _record_failure(self, communication_id: UUID, *, provider: str, error: str) -> None:
        """Best-effort failure evidence; a broken store must not abort the batch."""
        try:
            self._communications.record_dispatch_failure(
                communication_id, provider=provider, error=error
            )
        except Exception:
            logger.error(
                "messaging.dispatch_failure_record_failed",
                communication_id=str(communication_id),
                provider=provider,
                exc_info=True,
            )

    def _recipient(self, candidate_id: UUID, queued_recipient: str | None) -> str | None:
        if queued_recipient:
            return queued_recipient
        if self._directory is None:
            return None
        return self._directory.primary_email(candidate_id)
