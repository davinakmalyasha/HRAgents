"""WhatsApp Cloud dispatch: the queue, the lease, and the recorded evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from hr_agents.identity import ActorRef
from hr_agents.messaging.base import SendResult
from hr_agents.messaging.whatsapp_cloud import WhatsAppCloudDispatcher
from hr_agents.models import (
    CandidateCommunication,
    Channel,
    CommunicationStatus,
    DimensionScore,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.recruiting import CommunicationService, EvaluationService

CANDIDATE_ID = uuid4()
PHONE = "0812-3456-7890"
MOMENT = datetime(2026, 10, 31, 2, 0, tzinfo=UTC)


class FakeSender:
    provider_id = "whatsapp.meta_cloud"

    def __init__(self, *, accepted: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.accepted = accepted

    def send(self, *, phone: str, body: str) -> SendResult:
        self.calls.append((phone, body))
        if not self.accepted:
            return SendResult(
                provider=self.provider_id, accepted=False, detail="http 400: recipient invalid"
            )
        return SendResult(provider=self.provider_id, accepted=True, message_id="wamid.1")


def make_evaluation(candidate_id: UUID) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=0.9,
        stack_alignment=0.9,
        systems_literacy=0.9,
        verifiable_certifications=0.9,
    )
    return TechnicalEvaluation(
        candidate_id=candidate_id,
        job_id=uuid4(),
        runs=[
            ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector),
            ScoringRun(run_index=1, extraction_id=uuid4(), vector=vector),
        ],
        mean_vector=vector,
        s_tech=0.9,
        sigma=0.0,
        breakdown=[
            DimensionScore(dimension=dimension, score=0.9, weight=0.25, rationale="evidence")
            for dimension in ScoreDimension
        ],
        flags=[],
        recommendation=Recommendation.HUMAN_REVIEW,
    )


@pytest.fixture
def communications() -> CommunicationService:
    audit = AuditChain()
    evaluations = EvaluationService(audit=audit)
    evaluations.register(
        application_id=uuid4(),
        evaluation=make_evaluation(CANDIDATE_ID),
        candidate_name="Sari Dewi",
        job_title="Backend Engineer",
    )
    return CommunicationService(evaluations=evaluations, audit=audit)


def make_dispatcher(
    communications: CommunicationService, sender: FakeSender
) -> WhatsAppCloudDispatcher:
    return WhatsAppCloudDispatcher(communications=communications, sender=sender)


def queued(
    communications: CommunicationService,
    *,
    channel: Channel = Channel.WHATSAPP,
    phone: str | None = PHONE,
    body: str = "Halo, wawancara besok?",
) -> CandidateCommunication:
    return communications.queue_offer(
        CANDIDATE_ID,
        actor=ActorRef.legacy("hr-admin"),
        body=body,
        channel=channel,
        to_phone=phone,
    )


def test_dispatch_sends_whatsapp_only_and_records_the_evidence(
    communications: CommunicationService,
) -> None:
    whatsapp = queued(communications)
    other = uuid4()
    communications._evaluations.register(
        application_id=uuid4(),
        evaluation=make_evaluation(other),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )
    email = communications.queue_offer(
        other,
        actor=ActorRef.legacy("hr-admin"),
        body="Offer by email",
        to_email="budi@example.com",
    )
    sender = FakeSender()

    report = make_dispatcher(communications, sender).dispatch_pending(started_at=MOMENT)

    assert (report.sent, report.failed) == (1, 0)
    assert sender.calls == [(PHONE, "Halo, wawancara besok?")]
    refreshed = communications.get(whatsapp.id)
    assert refreshed.status is CommunicationStatus.SENT
    assert refreshed.provider == "whatsapp.meta_cloud"
    assert refreshed.provider_message_id == "wamid.1"
    assert refreshed.recipient_phone == PHONE
    assert refreshed.claimed_by is None
    # The email queue is a different dispatcher's business.
    assert communications.get(email.id).status is CommunicationStatus.QUEUED


def test_a_refusal_keeps_the_message_queued_with_the_error(
    communications: CommunicationService,
) -> None:
    item = queued(communications)

    report = make_dispatcher(communications, FakeSender(accepted=False)).dispatch_pending(
        started_at=MOMENT
    )

    assert (report.sent, report.failed) == (0, 1)
    refreshed = communications.get(item.id)
    assert refreshed.status is CommunicationStatus.QUEUED
    assert refreshed.send_attempts == 1
    assert refreshed.last_attempt_at is not None
    assert "recipient invalid" in (refreshed.last_error or "")


def test_a_message_without_a_number_is_skipped(communications: CommunicationService) -> None:
    item = queued(communications, phone=None)
    sender = FakeSender()

    report = make_dispatcher(communications, sender).dispatch_pending(started_at=MOMENT)

    assert (report.sent, report.skipped) == (0, 1)
    assert sender.calls == []
    assert communications.get(item.id).status is CommunicationStatus.QUEUED


def test_a_lease_held_by_another_run_is_skipped(communications: CommunicationService) -> None:
    item = queued(communications)
    assert communications.claim_for_dispatch(item.id, claimed_by="run-messaging") is not None
    sender = FakeSender()

    report = make_dispatcher(communications, sender).dispatch_pending(started_at=MOMENT)

    assert (report.sent, report.skipped) == (0, 1)
    assert sender.calls == []
    assert "another dispatcher" in report.outcomes[0].detail
