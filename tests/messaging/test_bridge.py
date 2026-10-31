"""Outbox dispatch and inbound reply ingestion.


Negative tests first: a message is only carried when a human queued it, an
address-less message is never sent, a failing transport leaves the queue intact,
and mail that matches no candidate is never attributed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from hr_agents.identity import ActorProvenance, ActorRef
from hr_agents.messaging.base import (
    InboundEmail,
    InboundWhatsApp,
    OutboundEmail,
    SendResult,
    TransportError,
)
from hr_agents.messaging.contacts import InMemoryCandidateDirectory
from hr_agents.messaging.inbound import ReplyIngestor
from hr_agents.messaging.outbox import OutboxDispatcher, default_subject, retry_delay
from hr_agents.messaging.store import ReplyStore
from hr_agents.models import (
    ActorType,
    ApproverRole,
    CandidateReply,
    Channel,
    CommunicationKind,
    CommunicationStatus,
    DimensionScore,
    PolicyDecision,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
)
from hr_agents.rbac import RoleId
from hr_agents.services import AuditChain
from hr_agents.services.recruiting import (
    CommunicationService,
    EvaluationService,
    RecruitingError,
)

CANDIDATE_ID = uuid4()
CANDIDATE_EMAIL = "budi@example.com"


class FakeSender:
    """Transport double: records what it was asked to send."""

    def __init__(
        self,
        *,
        accept: bool = True,
        provider_id: str = "email.smtp",
    ) -> None:
        self.sent: list[OutboundEmail] = []
        self.accept = accept
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def send(self, message: OutboundEmail) -> SendResult:
        self.sent.append(message)
        if not self.accept:
            return SendResult(
                provider=self._provider_id,
                accepted=False,
                detail="550 mailbox unavailable",
            )
        return SendResult(
            provider=self._provider_id,
            accepted=True,
            message_id="<outbound-1@example.com>",
        )


def make_evaluation(
    *, candidate_id: UUID = CANDIDATE_ID, s_tech: float = 0.90
) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=s_tech,
        stack_alignment=s_tech,
        systems_literacy=s_tech,
        verifiable_certifications=s_tech,
    )
    return TechnicalEvaluation(
        candidate_id=candidate_id,
        job_id=uuid4(),
        runs=[
            ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector),
            ScoringRun(run_index=1, extraction_id=uuid4(), vector=vector),
        ],
        mean_vector=vector,
        s_tech=s_tech,
        sigma=0.0,
        breakdown=[
            DimensionScore(dimension=dimension, score=s_tech, weight=0.25, rationale="evidence")
            for dimension in ScoreDimension
        ],
        flags=[],
        recommendation=Recommendation.AUTO_SCHEDULE,
    )


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


def signed_in(actor_id: str, role: RoleId) -> ActorRef:
    """An authenticated principal, shaped the way ``from_principal`` builds one.

    ``ActorRef`` has no ``human`` constructor on purpose: being a person is a
    property of how the actor arrived, and only the auth layer can assert that.
    """
    return ActorRef(
        actor_id=actor_id,
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=role.value,
    )


@pytest.fixture
def evaluations(audit: AuditChain) -> EvaluationService:
    return EvaluationService(audit=audit)


@pytest.fixture
def communications(evaluations: EvaluationService, audit: AuditChain) -> CommunicationService:
    return CommunicationService(evaluations=evaluations, audit=audit)


@pytest.fixture
def directory() -> InMemoryCandidateDirectory:
    return InMemoryCandidateDirectory()


def register(evaluations: EvaluationService, *, candidate_id: UUID = CANDIDATE_ID) -> None:
    evaluations.register(
        application_id=uuid4(),
        evaluation=make_evaluation(candidate_id=candidate_id),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )


# --- dispatch ---------------------------------------------------------------------


def test_dispatch_sends_queued_messages_and_records_evidence(
    evaluations: EvaluationService,
    communications: CommunicationService,
    directory: InMemoryCandidateDirectory,
) -> None:
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="We would like to offer you the role."
    )
    directory.add(CANDIDATE_ID, CANDIDATE_EMAIL)
    sender = FakeSender()
    dispatcher = OutboxDispatcher(communications=communications, sender=sender, directory=directory)

    report = dispatcher.dispatch_pending()

    assert (report.sent, report.failed, report.skipped) == (1, 0, 0)
    assert report.ok is True
    assert sender.sent[0].to == CANDIDATE_EMAIL
    assert sender.sent[0].body == "We would like to offer you the role."
    refreshed = communications.get(queued.id)
    assert refreshed.status is CommunicationStatus.SENT
    assert refreshed.provider == "email.smtp"
    assert refreshed.provider_message_id == "<outbound-1@example.com>"


def test_dispatch_uses_the_subject_queued_by_the_human(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    communications.queue_offer(
        CANDIDATE_ID,
        actor=ActorRef.legacy("hr-admin"),
        body="Offer body",
        subject="Offer — Backend Engineer",
        to_email=CANDIDATE_EMAIL,
    )
    sender = FakeSender()

    OutboxDispatcher(communications=communications, sender=sender).dispatch_pending()

    assert sender.sent[0].subject == "Offer — Backend Engineer"


def test_offer_without_a_subject_gets_a_neutral_default(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    sender = FakeSender()

    OutboxDispatcher(communications=communications, sender=sender).dispatch_pending()

    assert sender.sent[0].subject == default_subject(CommunicationKind.OFFER, "en")


def test_message_without_an_address_is_skipped_not_sent(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body"
    )
    sender = FakeSender()
    dispatcher = OutboxDispatcher(communications=communications, sender=sender)

    report = dispatcher.dispatch_pending()

    assert (report.sent, report.failed, report.skipped) == (0, 0, 1)
    assert sender.sent == []
    assert communications.get(queued.id).status is CommunicationStatus.QUEUED


def test_failed_send_keeps_the_message_queued_with_the_error(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    dispatcher = OutboxDispatcher(communications=communications, sender=FakeSender(accept=False))

    report = dispatcher.dispatch_pending()

    assert (report.sent, report.failed) == (0, 1)
    assert report.ok is False
    refreshed = communications.get(queued.id)
    assert refreshed.status is CommunicationStatus.QUEUED
    assert refreshed.send_attempts == 1
    assert refreshed.last_error == "550 mailbox unavailable"


def test_transport_error_is_recorded_and_the_run_continues(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    first = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="First", to_email="first@example.com"
    )
    other = uuid4()
    register(evaluations, candidate_id=other)
    second = communications.queue_offer(
        other, actor=ActorRef.legacy("hr-admin"), body="Second", to_email="second@example.com"
    )

    class FlakySender(FakeSender):
        def send(self, message: OutboundEmail) -> SendResult:
            if message.to == "first@example.com":
                raise TransportError("smtp connection refused")
            return super().send(message)

    dispatcher = OutboxDispatcher(communications=communications, sender=FlakySender())

    report = dispatcher.dispatch_pending()

    assert (report.sent, report.failed) == (1, 1)
    assert communications.get(first.id).send_attempts == 1
    assert communications.get(second.id).status is CommunicationStatus.SENT


def test_an_unexpected_sender_error_does_not_abandon_the_batch(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    """A third-party adapter may raise anything; the other messages still go."""
    register(evaluations)
    first = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="First", to_email="first@example.com"
    )
    other = uuid4()
    register(evaluations, candidate_id=other)
    second = communications.queue_offer(
        other, actor=ActorRef.legacy("hr-admin"), body="Second", to_email="second@example.com"
    )

    class ExplodingSender(FakeSender):
        def send(self, message: OutboundEmail) -> SendResult:
            if message.to == "first@example.com":
                raise RuntimeError("adapter bug, not a TransportError")
            return super().send(message)

    report = OutboxDispatcher(
        communications=communications, sender=ExplodingSender()
    ).dispatch_pending()

    assert (report.sent, report.failed) == (1, 1)
    assert report.ok is False
    assert communications.get(first.id).send_attempts == 1
    assert communications.get(second.id).status is CommunicationStatus.SENT


def test_a_message_that_is_no_longer_queued_is_skipped_not_sent(
    evaluations: EvaluationService,
    communications: CommunicationService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listing can be stale; a decided message must not go out twice."""
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    communications.record_dispatch(
        queued.id, provider="email.smtp", recipient=CANDIDATE_EMAIL, message_id="<one@example.com>"
    )
    monkeypatch.setattr(communications, "list_queued", lambda **_: [communications.get(queued.id)])
    sender = FakeSender()

    report = OutboxDispatcher(communications=communications, sender=sender).dispatch_pending()

    assert (report.sent, report.skipped) == (0, 1)
    assert sender.sent == []
    assert "no longer queued" in report.outcomes[0].detail


def test_a_sent_message_whose_record_cannot_land_is_ambiguous_not_retried(
    evaluations: EvaluationService,
    communications: CommunicationService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bytes left, the evidence did not: report it, never claim it failed."""
    register(evaluations)
    communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    sender = FakeSender()

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise RecruitingError("communication is sent; only a queued message can be recorded")

    monkeypatch.setattr(communications, "record_dispatch", refuse)
    report = OutboxDispatcher(communications=communications, sender=sender).dispatch_pending()

    assert (report.sent, report.failed, report.unrecorded) == (0, 0, 1)
    assert report.ok is False
    assert len(sender.sent) == 1
    assert "do not retry blindly" in report.outcomes[0].detail


def test_a_failed_message_cools_off_before_the_next_attempt(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    """A bounced address was retried every scheduler tick, forever."""
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    first = OutboxDispatcher(
        communications=communications, sender=FakeSender(accept=False)
    ).dispatch_pending()
    assert first.failed == 1
    assert communications.get(queued.id).last_attempt_at is not None

    recovered = FakeSender()
    dispatcher = OutboxDispatcher(communications=communications, sender=recovered)
    cooling = dispatcher.dispatch_pending()

    assert (cooling.sent, cooling.failed, cooling.deferred) == (0, 0, 1)
    assert cooling.ok is True
    assert recovered.sent == []

    attempt = communications.get(queued.id).last_attempt_at
    assert attempt is not None
    retried = dispatcher.dispatch_pending(started_at=attempt + retry_delay(1))

    assert retried.sent == 1
    assert [message.to for message in recovered.sent] == [CANDIDATE_EMAIL]


def test_retry_delay_doubles_and_is_capped() -> None:
    assert retry_delay(0) == timedelta(0)
    assert retry_delay(1) == timedelta(minutes=15)
    assert retry_delay(2) == timedelta(minutes=30)
    assert retry_delay(3) == timedelta(hours=1)
    assert retry_delay(50) == timedelta(hours=24)


def test_a_send_lease_is_exclusive_and_expires(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    moment = datetime(2026, 10, 31, 1, 0, tzinfo=UTC)

    first = communications.claim_for_dispatch(queued.id, claimed_by="dispatcher-a", now=moment)
    second = communications.claim_for_dispatch(queued.id, claimed_by="dispatcher-b", now=moment)

    assert first is not None
    assert first.claimed_by == "dispatcher-a"
    assert second is None

    reclaimed = communications.claim_for_dispatch(
        queued.id, claimed_by="dispatcher-b", now=moment + timedelta(minutes=11)
    )
    assert reclaimed is not None
    assert reclaimed.claimed_by == "dispatcher-b"


def test_a_sent_message_cannot_be_claimed_again(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    communications.mark_sent(queued.id, actor=signed_in("lead-1", RoleId.MANAGER))

    assert communications.claim_for_dispatch(queued.id, claimed_by="dispatcher-a") is None


def test_recording_the_outcome_clears_the_lease(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    claimed = communications.claim_for_dispatch(queued.id, claimed_by="dispatcher-a")
    assert claimed is not None

    communications.record_dispatch(
        queued.id,
        provider="email.smtp",
        recipient=CANDIDATE_EMAIL,
        message_id="<one@example.com>",
    )

    assert communications.get(queued.id).claimed_until is None
    assert communications.get(queued.id).claimed_by is None


def test_a_lease_held_by_another_dispatcher_is_skipped_not_sent(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    assert communications.claim_for_dispatch(queued.id, claimed_by="run-messaging") is not None
    sender = FakeSender()

    report = OutboxDispatcher(communications=communications, sender=sender).dispatch_pending()

    assert (report.sent, report.skipped) == (0, 1)
    assert sender.sent == []
    assert "another dispatcher" in report.outcomes[0].detail


def test_a_successful_dispatch_leaves_no_lease(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )

    OutboxDispatcher(communications=communications, sender=FakeSender()).dispatch_pending()

    refreshed = communications.get(queued.id)
    assert refreshed.claimed_by is None
    assert refreshed.claimed_until is None


def test_only_queued_email_messages_are_considered(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    communications.queue_offer(
        CANDIDATE_ID,
        actor=ActorRef.legacy("hr-admin"),
        body="WhatsApp body",
        channel=Channel.WHATSAPP,
        to_email=CANDIDATE_EMAIL,
    )
    sender = FakeSender()

    report = OutboxDispatcher(communications=communications, sender=sender).dispatch_pending()

    assert (report.sent, report.skipped, report.failed) == (0, 0, 0)
    assert sender.sent == []


def test_dispatch_respects_the_limit(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    for index in range(3):
        candidate = uuid4()
        register(evaluations, candidate_id=candidate)
        communications.queue_offer(
            candidate,
            actor=ActorRef.legacy("hr-admin"),
            body=f"Body {index}",
            to_email=f"c{index}@example.com",
        )
    sender = FakeSender()

    report = OutboxDispatcher(communications=communications, sender=sender).dispatch_pending(
        limit=2
    )

    assert report.sent == 2
    assert len(sender.sent) == 2


def test_preview_reports_readiness_without_sending(
    evaluations: EvaluationService,
    communications: CommunicationService,
    directory: InMemoryCandidateDirectory,
) -> None:
    register(evaluations)
    communications.queue_offer(CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body")
    sender = FakeSender()
    dispatcher = OutboxDispatcher(communications=communications, sender=sender, directory=directory)

    preview = dispatcher.preview()

    assert (preview.queued, preview.ready, preview.missing_recipient) == (1, 0, 1)
    assert sender.sent == []


def test_dispatch_audit_payload_keeps_the_approver(
    evaluations: EvaluationService, communications: CommunicationService, audit: AuditChain
) -> None:
    register(evaluations)
    communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("lead-1"), body="Offer body", to_email=CANDIDATE_EMAIL
    )

    OutboxDispatcher(communications=communications, sender=FakeSender()).dispatch_pending()

    entry = next(e for e in audit.entries if e.action == "communication.dispatched")
    assert entry.actor.actor_type is ActorType.SYSTEM
    assert entry.payload["approved_by"] == "lead-1"


def test_sandbox_sender_refuses_to_carry_anything(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    from hr_agents.messaging.runtime import DisabledEmailSender

    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    dispatcher = OutboxDispatcher(communications=communications, sender=DisabledEmailSender())

    report = dispatcher.dispatch_pending()

    assert (report.sent, report.failed) == (0, 1)
    assert communications.get(queued.id).status is CommunicationStatus.QUEUED
    with pytest.raises(TransportError):
        DisabledEmailSender().send(OutboundEmail(to=CANDIDATE_EMAIL, body="x"))


def test_rejection_approval_still_gates_dispatch(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    record = evaluations.register(
        application_id=uuid4(),
        evaluation=make_evaluation(s_tech=0.65),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )
    with pytest.raises(RecruitingError, match="recorded rejection decision"):
        communications.queue_rejection(
            CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), to_email=CANDIDATE_EMAIL
        )
    evaluations.record_override(
        record.evaluation.id,
        actor=signed_in("lead-1", RoleId.MANAGER),
        reviewer_role=ApproverRole.ENGINEERING_LEAD,
        override_decision=PolicyDecision.HITL_SOFT_REJECTION,
        reason_code="below_bar_after_review",
    )

    queued = communications.queue_rejection(
        CANDIDATE_ID, actor=ActorRef.legacy("lead-1"), to_email=CANDIDATE_EMAIL
    )
    OutboxDispatcher(communications=communications, sender=FakeSender()).dispatch_pending()

    assert communications.get(queued.id).approved_by == "lead-1"


# --- inbound ---------------------------------------------------------------------


def test_a_whatsapp_reply_is_attributed_by_the_number_it_answers(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    """There is no email address; the queued number is the thread."""
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID,
        actor=ActorRef.legacy("hr-admin"),
        body="Halo",
        channel=Channel.WHATSAPP,
        to_phone="0812-3456-7890",
    )
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications)

    report = ingestor.ingest_whatsapp(
        [
            InboundWhatsApp(
                phone="6281234567890", body="Saya terima tawarannya.", message_id="wamid.1"
            )
        ]
    )

    assert (report.matched, report.unmatched) == (1, 0)
    stored = replies.list_for(CANDIDATE_ID)
    assert stored[0].channel is Channel.WHATSAPP
    assert stored[0].communication_id == queued.id
    assert stored[0].sender == "6281234567890"


def test_a_whatsapp_reply_from_an_unknown_number_is_never_attributed(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications)

    report = ingestor.ingest_whatsapp(
        [InboundWhatsApp(phone="6289999999999", body="Halo?", message_id="wamid.9")]
    )

    assert (report.matched, report.unmatched) == (0, 1)
    assert replies.list_all() == []


def test_a_whatsapp_reply_is_stored_once_per_provider_message(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    communications.queue_offer(
        CANDIDATE_ID,
        actor=ActorRef.legacy("hr-admin"),
        body="Halo",
        channel=Channel.WHATSAPP,
        to_phone="081234567890",
    )
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications)
    message = InboundWhatsApp(phone="6281234567890", body="Terima kasih", message_id="wamid.1")

    ingestor.ingest_whatsapp([message])
    report = ingestor.ingest_whatsapp([message])

    assert report.duplicates == 1
    assert len(replies.list_for(CANDIDATE_ID)) == 1


def make_inbound(**overrides: object) -> InboundEmail:
    payload: dict[str, object] = {
        "provider": "email.imap_poll",
        "from_address": CANDIDATE_EMAIL,
        "to_address": "hr@example.com",
        "subject": "Re: Your offer",
        "body": "I accept the offer, thank you.",
        "message_id": "<reply-1@example.com>",
    }
    payload.update(overrides)
    return InboundEmail(**payload)  # type: ignore[arg-type]


def test_reply_is_attributed_by_the_message_it_answers(
    evaluations: EvaluationService, communications: CommunicationService, audit: AuditChain
) -> None:
    register(evaluations)
    queued = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body", to_email=CANDIDATE_EMAIL
    )
    communications.record_dispatch(
        queued.id,
        provider="email.smtp",
        recipient=CANDIDATE_EMAIL,
        message_id="<outbound-1@example.com>",
    )
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications, audit=audit)

    report = ingestor.ingest([make_inbound(in_reply_to="<outbound-1@example.com>")])

    assert (report.matched, report.unmatched) == (1, 0)
    stored = replies.list_for(CANDIDATE_ID)
    assert len(stored) == 1
    assert stored[0].communication_id == queued.id
    assert any(entry.action == "communication.reply_received" for entry in audit.entries)


def test_reply_is_attributed_by_sender_when_threading_is_missing(
    evaluations: EvaluationService,
    communications: CommunicationService,
    directory: InMemoryCandidateDirectory,
) -> None:
    register(evaluations)
    directory.add(CANDIDATE_ID, CANDIDATE_EMAIL.upper())
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications, directory=directory)

    report = ingestor.ingest([make_inbound()])

    assert (report.matched, report.unmatched) == (1, 0)
    assert replies.list_for(CANDIDATE_ID)[0].communication_id is None


def test_unknown_sender_is_never_stored(
    evaluations: EvaluationService,
    communications: CommunicationService,
    directory: InMemoryCandidateDirectory,
) -> None:
    register(evaluations)
    directory.add(CANDIDATE_ID, CANDIDATE_EMAIL)
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications, directory=directory)

    report = ingestor.ingest([make_inbound(from_address="stranger@elsewhere.com")])

    assert (report.matched, report.unmatched) == (0, 1)
    assert replies.list_all() == []


def test_bodyless_mail_is_never_stored_as_a_reply(
    evaluations: EvaluationService, communications: CommunicationService, audit: AuditChain
) -> None:
    register(evaluations)
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications, audit=audit)

    report = ingestor.ingest([make_inbound(body="")])

    assert (report.matched, report.unmatched) == (0, 1)
    assert replies.list_all() == []


def test_repolling_the_same_message_stores_it_once(
    evaluations: EvaluationService,
    communications: CommunicationService,
    directory: InMemoryCandidateDirectory,
) -> None:
    register(evaluations)
    directory.add(CANDIDATE_ID, CANDIDATE_EMAIL)
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications, directory=directory)
    message = make_inbound()

    ingestor.ingest([message])
    report = ingestor.ingest([message])

    assert (report.matched, report.duplicates) == (0, 1)
    assert len(replies.list_for(CANDIDATE_ID)) == 1


def test_reply_without_a_message_id_is_deduplicated_by_content(
    evaluations: EvaluationService,
    communications: CommunicationService,
    directory: InMemoryCandidateDirectory,
) -> None:
    register(evaluations)
    directory.add(CANDIDATE_ID, CANDIDATE_EMAIL)
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications, directory=directory)
    message = make_inbound(message_id=None)

    ingestor.ingest([message])
    report = ingestor.ingest([message])

    assert report.duplicates == 1
    assert len(replies.list_for(CANDIDATE_ID)) == 1


def test_a_reply_is_evidence_never_a_decision(
    evaluations: EvaluationService,
    communications: CommunicationService,
    directory: InMemoryCandidateDirectory,
) -> None:
    register(evaluations)
    directory.add(CANDIDATE_ID, CANDIDATE_EMAIL)
    replies = ReplyStore()
    ingestor = ReplyIngestor(replies=replies, communications=communications, directory=directory)

    ingestor.ingest([make_inbound(body="I accept the offer, thank you.")])

    assert communications.list_queued() == []
    assert all(isinstance(reply, CandidateReply) for reply in replies.list_all())


def test_reply_ingest_audit_actor_is_the_transport(
    evaluations: EvaluationService,
    communications: CommunicationService,
    directory: InMemoryCandidateDirectory,
    audit: AuditChain,
) -> None:
    register(evaluations)
    directory.add(CANDIDATE_ID, CANDIDATE_EMAIL)
    ingestor = ReplyIngestor(
        replies=ReplyStore(),
        communications=communications,
        directory=directory,
        audit=audit,
    )

    ingestor.ingest([make_inbound()])

    entry = next(e for e in audit.entries if e.action == "communication.reply_received")
    assert entry.actor.actor_type is ActorType.SYSTEM
    # Prefixed, so `classify_actor` agrees with the type: a bare
    # `AuditActor(actor_type=SYSTEM, actor_id="transport:...")` left the id and
    # the type telling an auditor different stories, and defaulted `provenance`
    # to `LEGACY_STRING` -- the weakest claim -- for an entry nobody was present
    # to make.
    assert entry.actor.actor_id == "system:transport:email.imap_poll"
    assert entry.actor.provenance is ActorProvenance.SYSTEM_JOB
