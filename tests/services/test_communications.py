"""Candidate communication queueing rules.


Negative tests first: a message cannot be queued without its recorded decision,
without a named human, or twice while an earlier one is still active.
"""

from uuid import UUID, uuid4

import pytest

from hr_agents.identity import ActorRef
from hr_agents.models import (
    ActorType,
    CandidateCommunication,
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
from hr_agents.services import AuditChain
from hr_agents.services.recruiting import (
    CommunicationService,
    EvaluationRecord,
    EvaluationService,
    RecruitingError,
    compose_rejection_body,
    synthesize_feedback,
)

CANDIDATE_ID = uuid4()


def make_evaluation(
    *,
    candidate_id: UUID = CANDIDATE_ID,
    s_tech: float = 0.90,
    sigma: float = 0.0,
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
        sigma=sigma,
        breakdown=[
            DimensionScore(dimension=dimension, score=s_tech, weight=0.25, rationale="evidence")
            for dimension in ScoreDimension
        ],
        flags=[],
        recommendation=Recommendation.REJECT if s_tech < 0.70 else Recommendation.AUTO_SCHEDULE,
    )


@pytest.fixture
def audit() -> AuditChain:
    return AuditChain()


@pytest.fixture
def evaluations(audit: AuditChain) -> EvaluationService:
    return EvaluationService(audit=audit)


@pytest.fixture
def communications(evaluations: EvaluationService, audit: AuditChain) -> CommunicationService:
    return CommunicationService(evaluations=evaluations, audit=audit)


def register(
    evaluations: EvaluationService,
    *,
    candidate_id: UUID = CANDIDATE_ID,
    s_tech: float = 0.90,
) -> EvaluationRecord:
    return evaluations.register(
        application_id=uuid4(),
        evaluation=make_evaluation(candidate_id=candidate_id, s_tech=s_tech),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )


# --- rejection queueing ----------------------------------------------------------


def test_rejection_requires_a_recorded_decision(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations, s_tech=0.80)  # soft-rejection band, no override recorded

    with pytest.raises(RecruitingError, match="recorded rejection decision"):
        communications.queue_rejection(CANDIDATE_ID, actor=ActorRef.legacy("lead-1"))


def test_rejection_after_override_queues_a_grounded_message(
    evaluations: EvaluationService, communications: CommunicationService, audit: AuditChain
) -> None:
    record = register(evaluations, s_tech=0.80)
    evaluations.record_override(
        record.evaluation.id,
        reviewer_id="lead-1",
        reviewer_role="engineering_lead",
        override_decision=PolicyDecision.HITL_SOFT_REJECTION,
        reason_code="below_bar_after_review",
    )

    item = communications.queue_rejection(
        CANDIDATE_ID, actor=ActorRef.legacy("lead-1"), language="id"
    )

    assert item.status is CommunicationStatus.QUEUED
    assert item.kind is CommunicationKind.REJECTION
    assert item.approved_by == "lead-1"
    assert item.subject is not None and "Backend Engineer" in item.subject
    assert "Yang menonjol" in item.body
    assert "Laporan ini merangkum" in item.body
    assert "0.8" not in item.body
    assert "technical_depth" not in item.body
    assert any(entry.action == "communication.queued" for entry in audit.entries)


def test_documented_auto_rejection_queues_without_an_override(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations, s_tech=0.50)

    item = communications.queue_rejection(CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"))

    assert item.language == "en"
    assert "Where to strengthen" in item.body


def test_rejection_rejects_agent_actors(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations, s_tech=0.50)

    with pytest.raises(RecruitingError, match="named human"):
        communications.queue_rejection(
            CANDIDATE_ID, actor=ActorRef.legacy("agent:screening_coordinator")
        )


def test_rejection_requires_an_evaluation(communications: CommunicationService) -> None:
    with pytest.raises(RecruitingError, match="no evaluation"):
        communications.queue_rejection(uuid4(), actor=ActorRef.legacy("hr-admin"))


def test_duplicate_active_rejection_is_blocked(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations, s_tech=0.50)
    communications.queue_rejection(CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"))

    with pytest.raises(RecruitingError, match="already exists"):
        communications.queue_rejection(CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"))


# --- offer queueing --------------------------------------------------------------


def test_offer_requires_a_named_human_and_a_body(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)

    with pytest.raises(RecruitingError, match="named human"):
        communications.queue_offer(
            CANDIDATE_ID, actor=ActorRef.legacy("agent:policy_assistant"), body="Hello"
        )
    with pytest.raises(RecruitingError, match="body is required"):
        communications.queue_offer(CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="   ")


def test_offer_queues_with_the_named_approver(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)

    item = communications.queue_offer(
        CANDIDATE_ID,
        actor=ActorRef.legacy("hr-admin"),
        body="We would like to offer you the role, starting 1 November.",
        subject="Offer — Backend Engineer",
    )

    assert item.kind is CommunicationKind.OFFER
    assert item.approved_by == "hr-admin"
    assert item.body.startswith("We would like")
    assert item.sent_at is None


def test_only_one_active_offer_per_candidate(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    communications.queue_offer(CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="First")

    with pytest.raises(RecruitingError, match="already exists"):
        communications.queue_offer(CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Second")


# --- dispatch evidence -----------------------------------------------------------


def test_mark_sent_records_manual_dispatch_once(
    evaluations: EvaluationService, communications: CommunicationService, audit: AuditChain
) -> None:
    register(evaluations)
    item = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body"
    )

    sent = communications.mark_sent(item.id, actor=ActorRef.legacy("hr-admin"))

    assert sent.status is CommunicationStatus.SENT
    assert sent.sent_by == "hr-admin"
    assert sent.sent_at is not None
    assert any(entry.action == "communication.sent" for entry in audit.entries)

    with pytest.raises(RecruitingError, match="only a queued message"):
        communications.mark_sent(item.id, actor=ActorRef.legacy("hr-admin"))


def test_mark_sent_requires_a_named_human(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    item = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body"
    )

    with pytest.raises(RecruitingError, match="named human"):
        communications.mark_sent(item.id, actor=ActorRef.legacy("agent:screening_coordinator"))


def test_list_for_filters_by_candidate(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    other = uuid4()
    register(evaluations, s_tech=0.50)
    register(evaluations, candidate_id=other, s_tech=0.50)
    mine = communications.queue_rejection(CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"))
    communications.queue_rejection(other, actor=ActorRef.legacy("hr-admin"))

    items = communications.list_for(CANDIDATE_ID)

    assert [item.id for item in items] == [mine.id]
    assert all(isinstance(item, CandidateCommunication) for item in items)


# --- transport dispatch evidence --------------------------------------------------


def test_dispatch_records_provider_evidence(
    evaluations: EvaluationService, communications: CommunicationService, audit: AuditChain
) -> None:
    register(evaluations)
    item = communications.queue_offer(
        CANDIDATE_ID,
        actor=ActorRef.legacy("hr-admin"),
        body="Offer body",
        to_email="budi@example.com",
    )

    sent = communications.record_dispatch(
        item.id,
        provider="email.smtp",
        recipient="budi@example.com",
        message_id="<outbound-1@example.com>",
    )

    assert sent.status is CommunicationStatus.SENT
    assert sent.sent_by == "transport:email.smtp"
    assert sent.provider == "email.smtp"
    assert sent.provider_message_id == "<outbound-1@example.com>"
    assert sent.recipient == "budi@example.com"
    assert sent.send_attempts == 1
    assert sent.last_error is None
    dispatched = next(e for e in audit.entries if e.action == "communication.dispatched")
    assert dispatched.actor.actor_type is ActorType.SYSTEM
    assert dispatched.payload["approved_by"] == "hr-admin"


def test_dispatch_failure_keeps_the_message_queued(
    evaluations: EvaluationService, communications: CommunicationService, audit: AuditChain
) -> None:
    register(evaluations)
    item = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body"
    )

    after = communications.record_dispatch_failure(
        item.id, provider="email.smtp", error="mailbox unavailable"
    )

    assert after.status is CommunicationStatus.QUEUED
    assert after.send_attempts == 1
    assert after.last_error == "mailbox unavailable"
    assert any(e.action == "communication.dispatch_failed" for e in audit.entries)


def test_a_sent_message_is_never_dispatched_again(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    item = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="Offer body"
    )
    communications.mark_sent(item.id, actor=ActorRef.legacy("hr-admin"))

    with pytest.raises(RecruitingError, match="only a queued message"):
        communications.record_dispatch(item.id, provider="email.smtp", recipient="budi@example.com")


def test_list_queued_excludes_sent_messages(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    first = communications.queue_offer(
        CANDIDATE_ID, actor=ActorRef.legacy("hr-admin"), body="First"
    )
    other = uuid4()
    register(evaluations, candidate_id=other)
    second = communications.queue_offer(other, actor=ActorRef.legacy("hr-admin"), body="Second")
    communications.mark_sent(first.id, actor=ActorRef.legacy("hr-admin"))

    queued = communications.list_queued()

    assert [item.id for item in queued] == [second.id]
    assert communications.list_queued(channel=Channel.WHATSAPP) == []


def test_reply_threading_finds_the_message_by_provider_id(
    evaluations: EvaluationService, communications: CommunicationService
) -> None:
    register(evaluations)
    item = communications.queue_offer(
        CANDIDATE_ID,
        actor=ActorRef.legacy("hr-admin"),
        body="Offer body",
        to_email="budi@example.com",
    )
    communications.record_dispatch(
        item.id,
        provider="email.smtp",
        recipient="budi@example.com",
        message_id="<Outbound-1@Example.com>",
    )

    found = communications.find_by_provider_message_id("<outbound-1@example.com>")

    assert found is not None and found.id == item.id
    assert communications.find_by_provider_message_id("<unknown@example.com>") is None


# --- composition -----------------------------------------------------------------


def test_compose_rejection_body_carries_no_scores() -> None:
    report = synthesize_feedback(
        make_evaluation(s_tech=0.55),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
        language="en",
    )

    body = compose_rejection_body(report)

    assert "Where to strengthen:" in body
    assert "0.55" not in body
    assert report.correction_notice in body
