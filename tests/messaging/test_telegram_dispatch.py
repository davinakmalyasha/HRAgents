"""Telegram dispatch: the chat-id address, the lease, and the evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from hr_agents.identity import ActorRef
from hr_agents.messaging.base import SendResult
from hr_agents.messaging.telegram import TelegramDispatcher
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
CHAT_ID = "55501"
MOMENT = datetime(2026, 10, 31, 4, 0, tzinfo=UTC)


class FakeSender:
    provider_id = "telegram.bot"

    def __init__(self, *, accepted: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.accepted = accepted

    def send(self, *, chat_id: str, body: str) -> SendResult:
        self.calls.append((chat_id, body))
        if not self.accepted:
            return SendResult(
                provider=self.provider_id, accepted=False, detail="http 403: bot was blocked"
            )
        return SendResult(provider=self.provider_id, accepted=True, message_id="77")


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


def queued(
    communications: CommunicationService,
    *,
    chat_id: str | None = CHAT_ID,
    body: str = "Halo, wawancara besok?",
) -> CandidateCommunication:
    return communications.queue_offer(
        CANDIDATE_ID,
        actor=ActorRef.legacy("hr-admin"),
        body=body,
        channel=Channel.TELEGRAM,
        to_telegram_chat_id=chat_id,
    )


def test_dispatch_sends_telegram_only_and_records_the_chat_id(
    communications: CommunicationService,
) -> None:
    telegram = queued(communications)
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

    report = TelegramDispatcher(communications=communications, sender=sender).dispatch_pending(
        started_at=MOMENT
    )

    assert (report.sent, report.failed) == (1, 0)
    assert sender.calls == [(CHAT_ID, "Halo, wawancara besok?")]
    refreshed = communications.get(telegram.id)
    assert refreshed.status is CommunicationStatus.SENT
    assert refreshed.provider == "telegram.bot"
    assert refreshed.provider_message_id == "77"
    assert refreshed.recipient_telegram_chat_id == CHAT_ID
    assert refreshed.claimed_by is None
    assert communications.get(email.id).status is CommunicationStatus.QUEUED


def test_a_refusal_keeps_the_message_queued(communications: CommunicationService) -> None:
    item = queued(communications)

    report = TelegramDispatcher(
        communications=communications, sender=FakeSender(accepted=False)
    ).dispatch_pending(started_at=MOMENT)

    assert (report.sent, report.failed) == (0, 1)
    refreshed = communications.get(item.id)
    assert refreshed.status is CommunicationStatus.QUEUED
    assert refreshed.send_attempts == 1
    assert "blocked" in (refreshed.last_error or "")


def test_a_message_without_a_chat_id_is_skipped(communications: CommunicationService) -> None:
    item = queued(communications, chat_id=None)
    sender = FakeSender()

    report = TelegramDispatcher(communications=communications, sender=sender).dispatch_pending(
        started_at=MOMENT
    )

    assert (report.sent, report.skipped) == (0, 1)
    assert sender.calls == []
    assert communications.get(item.id).status is CommunicationStatus.QUEUED


def test_a_lease_held_by_another_run_is_skipped(communications: CommunicationService) -> None:
    item = queued(communications)
    assert communications.claim_for_dispatch(item.id, claimed_by="run-messaging") is not None
    sender = FakeSender()

    report = TelegramDispatcher(communications=communications, sender=sender).dispatch_pending(
        started_at=MOMENT
    )

    assert (report.sent, report.skipped) == (0, 1)
    assert sender.calls == []
    assert "another dispatcher" in report.outcomes[0].detail
