"""Offer records — terms revisions, the approval gate, and acceptance tracking.

The system never invents terms, never approves on its own, and never accepts
on a candidate's behalf: every transition requires a named human, sits on the
shared audit chain, and the acceptance outcome is recorded, not automated.
Approval routes through the shared engine (``ApprovalSubject.OFFER``); the
offer message itself is queued through the communication outbox.

Database adapters override the ``_load``/``_iter``/``_persist`` primitives.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from hr_agents.models import (
    EXPIRABLE_OFFER_STATUSES,
    ActorType,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    AuditActor,
    Offer,
    OfferRevision,
    OfferStatus,
    OfferTerms,
)
from hr_agents.services.approvals import ApprovalError
from hr_agents.services.audit import AuditChain

if TYPE_CHECKING:
    from hr_agents.services.approvals import ApprovalEngine
    from hr_agents.services.ingestion import ApplicationStore
    from hr_agents.services.recruiting import CommunicationService, EvaluationService

AGENT_ACTOR_PREFIX = "agent:"

_OFFER_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "opening": "We are pleased to offer you the position of {position} ({employment_type}).",
        "start": "Start date: {start_date}",
        "end": "End date: {end_date}",
        "probation": "Probation: {months} month(s)",
        "compensation": "Compensation: {currency} {amount}",
        "valid": "This offer is valid until {expires}.",
        "closing": "Please reply to confirm your decision — we look forward to hearing from you.",
    },
    "id": {
        "opening": "Dengan senang hati kami menawarkan posisi {position} ({employment_type}).",
        "start": "Tanggal mulai: {start_date}",
        "end": "Tanggal berakhir: {end_date}",
        "probation": "Masa percobaan: {months} bulan",
        "compensation": "Kompensasi: {currency} {amount}",
        "valid": "Tawaran ini berlaku sampai {expires}.",
        "closing": "Silakan balas untuk mengonfirmasi keputusan Anda — kami menantikan kabarnya.",
    },
}


def compose_offer_body(terms: OfferTerms, *, language: str = "en") -> str:
    """Deterministic message draft from human-entered terms (editable by the sender)."""
    lang = "id" if language == "id" else "en"
    labels = _OFFER_TEMPLATES[lang]
    lines = [
        labels["opening"].format(
            position=terms.position_title,
            employment_type=terms.employment_type.value.upper(),
        ),
        "",
        labels["start"].format(start_date=terms.start_date.isoformat()),
    ]
    if terms.end_date is not None:
        lines.append(labels["end"].format(end_date=terms.end_date.isoformat()))
    if terms.probation_months is not None:
        lines.append(labels["probation"].format(months=terms.probation_months))
    lines.append(
        labels["compensation"].format(
            currency=terms.salary_currency,
            amount=f"{terms.salary_amount:,.2f}",
        )
    )
    if terms.notes.strip():
        lines.append("")
        lines.append(terms.notes.strip())
    if terms.expires_at is not None:
        lines.append("")
        lines.append(labels["valid"].format(expires=terms.expires_at.date().isoformat()))
    lines.append("")
    lines.append(labels["closing"])
    return "\n".join(lines)


class OfferError(RuntimeError):
    """Invalid offer operation; the router maps messages to HTTP statuses."""


class OfferService:
    """Offer records behind the approval gate, with acceptance tracking."""

    def __init__(
        self,
        *,
        evaluations: EvaluationService,
        communications: CommunicationService,
        audit: AuditChain | None = None,
        approvals: ApprovalEngine | None = None,
        applications: ApplicationStore | None = None,
    ) -> None:
        self._evaluations = evaluations
        self._communications = communications
        self._approvals = approvals
        self._applications = applications
        self._audit = audit or AuditChain()
        self._offers: dict[UUID, Offer] = {}

    # persistence primitives (overridden by database adapters)

    def _load(self, offer_id: UUID) -> Offer | None:
        return self._offers.get(offer_id)

    def _iter(self) -> list[Offer]:
        return list(self._offers.values())

    def _persist(self, offer: Offer) -> None:
        self._offers[offer.id] = offer

    # creation & revisions

    def create(self, application_id: UUID, terms: OfferTerms, *, by: str, note: str = "") -> Offer:
        """Create a draft offer; the evaluation supplies candidate and job."""
        actor = self._require_human(by)
        record = self._evaluations.get_by_application(application_id)
        offer = Offer(
            application_id=application_id,
            candidate_id=record.candidate_id,
            job_id=record.job_id,
            terms=terms,
            created_by=actor,
        )
        revision = OfferRevision(
            offer_id=offer.id,
            revision_index=1,
            terms=terms,
            changed_by=actor,
            note=note.strip(),
        )
        offer = offer.model_copy(update={"revisions": [revision]})
        self._persist(offer)
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=actor),
            action="offer.created",
            subject_type="offer",
            subject_id=str(offer.id),
            payload={
                "application_id": str(application_id),
                "candidate_id": str(record.candidate_id),
                "employment_type": terms.employment_type.value,
                "has_end_date": terms.end_date is not None,
            },
        )
        return offer

    def revise(self, offer_id: UUID, terms: OfferTerms, *, by: str, note: str = "") -> Offer:
        """Revise a draft offer; each revision is an append-only snapshot."""
        actor = self._require_human(by)
        offer = self.get(offer_id)
        if offer.status is not OfferStatus.DRAFT:
            raise OfferError("only draft offers can be revised; withdraw and create a new one")
        revision = OfferRevision(
            offer_id=offer.id,
            revision_index=len(offer.revisions) + 1,
            terms=terms,
            changed_by=actor,
            note=note.strip(),
        )
        updated = offer.model_copy(
            update={
                "terms": terms,
                "revisions": [*offer.revisions, revision],
                "updated_at": datetime.now(UTC),
            }
        )
        self._persist(updated)
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=actor),
            action="offer.revised",
            subject_type="offer",
            subject_id=str(offer.id),
            payload={"revision_index": revision.revision_index},
        )
        return updated

    # approval gate

    def submit(self, offer_id: UUID, *, by: str) -> Offer:
        """Send the draft to the approval queue as a named human."""
        actor = self._require_human(by)
        offer = self.get(offer_id)
        if offer.status is not OfferStatus.DRAFT:
            raise OfferError(f"offer is {offer.status.value}; only a draft can be submitted")
        updated = offer.model_copy(
            update={"status": OfferStatus.PENDING_APPROVAL, "updated_at": datetime.now(UTC)}
        )
        self._persist(updated)
        if self._approvals is not None:
            self._approvals.create(
                subject=ApprovalSubject.OFFER,
                subject_id=str(offer.id),
                title=f"Approve the offer for candidate {str(offer.candidate_id)[:8]}",
                summary=(
                    f"{offer.terms.position_title} · {offer.terms.employment_type.value.upper()} · "
                    f"starts {offer.terms.start_date.isoformat()}"
                ),
                assignee_role=ApproverRole.HR_ADMIN,
                requested_by=actor,
                payload={
                    "offer_id": str(offer.id),
                    "application_id": str(offer.application_id),
                    "candidate_id": str(offer.candidate_id),
                },
            )
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=actor),
            action="offer.submitted",
            subject_type="offer",
            subject_id=str(offer.id),
            payload={},
        )
        return updated

    def decide(self, offer_id: UUID, *, decision: str, by: str, reason: str = "") -> Offer:
        """Approve or withdraw an offer as a named human (single writer)."""
        if decision not in {"approve", "withdraw"}:
            raise OfferError(f"unknown decision {decision!r}")
        actor = self._require_human(by)
        offer = self.get(offer_id)
        if offer.is_terminal:
            raise OfferError(f"offer is {offer.status.value}; it cannot be decided again")

        approval = self._find_linked_approval(offer.id)

        if decision == "approve":
            if offer.status is OfferStatus.APPROVED:
                return offer
            if offer.status is not OfferStatus.PENDING_APPROVAL:
                raise OfferError(
                    f"offer is {offer.status.value}; only a pending offer can be approved"
                )
            self._decide_linked_approval(approval, by=actor, reason=reason)
            updated = offer.model_copy(
                update={
                    "status": OfferStatus.APPROVED,
                    "decided_by": actor,
                    "decided_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            )
            self._persist(updated)
            self._audit.append(
                actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=actor),
                action="offer.approved",
                subject_type="offer",
                subject_id=str(offer.id),
                payload={
                    "approval": approval.status.value if approval is not None else "none",
                    "reason_present": bool(reason.strip()),
                },
            )
            return updated

        if not reason.strip():
            raise OfferError("a reason is required to withdraw an offer")
        self._withdraw_linked_approval(approval, by=actor, reason=reason)
        updated = offer.model_copy(
            update={
                "status": OfferStatus.WITHDRAWN,
                "decided_by": actor,
                "decided_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        )
        self._persist(updated)
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=actor),
            action="offer.withdrawn",
            subject_type="offer",
            subject_id=str(offer.id),
            payload={"reason": reason.strip()},
        )
        return updated

    # messaging & acceptance

    def queue_message(
        self,
        offer_id: UUID,
        *,
        by: str,
        body: str | None = None,
        subject: str | None = None,
        language: str = "en",
    ) -> Offer:
        """Queue the candidate-facing offer message through the outbox."""
        actor = self._require_human(by)
        offer = self.get(offer_id)
        if offer.status is OfferStatus.QUEUED:
            raise OfferError("the offer message is already queued")
        if offer.status is not OfferStatus.APPROVED:
            raise OfferError(f"offer is {offer.status.value}; only an approved offer can be sent")
        message = (body or "").strip() or compose_offer_body(offer.terms, language=language)
        communication = self._communications.queue_offer(
            offer.candidate_id,
            by=actor,
            body=message,
            subject=subject,
            language=language,
        )
        updated = offer.model_copy(
            update={
                "status": OfferStatus.QUEUED,
                "queued_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        )
        self._persist(updated)
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=actor),
            action="offer.message_queued",
            subject_type="offer",
            subject_id=str(offer.id),
            payload={"communication_id": str(communication.id), "language": communication.language},
        )
        return updated

    def record_acceptance(
        self, offer_id: UUID, *, by: str, accepted: bool, reason: str = ""
    ) -> Offer:
        """Record the candidate's decision (a human relays it; nothing auto-accepts)."""
        actor = self._require_human(by)
        offer = self.get(offer_id)
        if offer.status not in {OfferStatus.APPROVED, OfferStatus.QUEUED}:
            raise OfferError(
                f"offer is {offer.status.value}; acceptance is recorded on approved offers"
            )
        if not accepted and not reason.strip():
            raise OfferError("a reason is required to record a declined offer")
        moment = datetime.now(UTC)
        update: dict[str, object] = {
            "status": OfferStatus.ACCEPTED if accepted else OfferStatus.DECLINED,
            "updated_at": moment,
        }
        if accepted:
            update["accepted_at"] = moment
        else:
            update["declined_at"] = moment
            update["decline_reason"] = reason.strip()
        updated = offer.model_copy(update=update)
        self._persist(updated)
        self._note_application(updated, "offer.accepted" if accepted else "offer.declined")
        self._audit.append(
            actor=AuditActor(actor_type=ActorType.HUMAN, actor_id=actor),
            action="offer.accepted" if accepted else "offer.declined",
            subject_type="offer",
            subject_id=str(offer.id),
            payload={"reason_present": bool(reason.strip())},
        )
        return updated

    # time-driven

    def expire_overdue(self, *, now: datetime | None = None) -> list[Offer]:
        """Expire stale offers; a scheduler calls this, the service performs no timers."""
        moment = now or datetime.now(UTC)
        expired: list[Offer] = []
        for offer in self._iter():
            if offer.status not in EXPIRABLE_OFFER_STATUSES:
                continue
            if offer.terms.expires_at is None or offer.terms.expires_at > moment:
                continue
            updated = offer.model_copy(
                update={
                    "status": OfferStatus.EXPIRED,
                    "decided_at": moment,
                    "updated_at": moment,
                }
            )
            self._persist(updated)
            self._audit.append(
                actor=AuditActor(actor_type=ActorType.SYSTEM, actor_id="system"),
                action="offer.expired",
                subject_type="offer",
                subject_id=str(offer.id),
                payload={"expires_at": offer.terms.expires_at.isoformat()},
            )
            expired.append(updated)
        return expired

    # queries & internals

    def get(self, offer_id: UUID) -> Offer:
        offer = self._load(offer_id)
        if offer is None:
            raise OfferError(f"unknown offer {offer_id}")
        return offer

    def list_all(self, *, application_id: UUID | None = None) -> list[Offer]:
        offers = sorted(self._iter(), key=lambda item: item.created_at)
        if application_id is None:
            return offers
        return [offer for offer in offers if offer.application_id == application_id]

    def _note_application(self, offer: Offer, event: str) -> None:
        if self._applications is None:
            return
        application = self._applications.get(offer.application_id)
        if application is None:
            return
        application.note(event)
        self._applications.save(application)

    def _find_linked_approval(self, offer_id: UUID) -> ApprovalRequest | None:
        if self._approvals is None:
            return None
        return self._approvals.find_by_subject(ApprovalSubject.OFFER, str(offer_id))

    def _decide_linked_approval(
        self, approval: ApprovalRequest | None, *, by: str, reason: str
    ) -> None:
        if approval is None or self._approvals is None:
            return
        if approval.status is ApprovalStatus.REJECTED:
            raise OfferError("the linked offer approval was rejected; create a new offer instead")
        if not approval.active:
            return
        try:
            self._approvals.decide(
                approval.id,
                decided_by=by,
                approve=True,
                reason=reason.strip() or "offer approved",
            )
        except ApprovalError as exc:
            raise OfferError(str(exc)) from exc

    def _withdraw_linked_approval(
        self, approval: ApprovalRequest | None, *, by: str, reason: str
    ) -> None:
        if approval is None or self._approvals is None or not approval.active:
            return
        try:
            self._approvals.withdraw(approval.id, by=by, reason=reason.strip() or None)
        except ApprovalError as exc:
            raise OfferError(str(exc)) from exc

    @staticmethod
    def _require_human(actor: str) -> str:
        cleaned = actor.strip()
        if not cleaned or cleaned.startswith(AGENT_ACTOR_PREFIX):
            raise OfferError("offers require a named human actor")
        return cleaned
