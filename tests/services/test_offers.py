"""Offer records: terms revisions, approval gate, acceptance tracking.


Negative tests first — no offer without a named human, no approval without the
queue, no acceptance before approval, and terminal offers stay terminal.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from hr_agents.identity import ActorRef
from hr_agents.models import (
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    CommunicationKind,
    CommunicationStatus,
    ContractType,
    DimensionScore,
    OfferStatus,
    OfferTerms,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
)
from hr_agents.services import ApplicationStore, AuditChain, SubmissionInput
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.offers import OfferError, OfferService, compose_offer_body
from hr_agents.services.people_store import ApprovalStore
from hr_agents.services.recruiting import (
    CommunicationService,
    EvaluationService,
    RecruitingError,
)

START = date(2026, 11, 1)
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@dataclass
class World:
    audit: AuditChain
    applications: ApplicationStore
    evaluations: EvaluationService
    approvals: ApprovalEngine
    communications: CommunicationService
    offers: OfferService
    application_id: UUID
    candidate_id: UUID


def make_evaluation(candidate_id: UUID) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=0.90,
        stack_alignment=0.90,
        systems_literacy=0.90,
        verifiable_certifications=0.90,
    )
    return TechnicalEvaluation(
        candidate_id=candidate_id,
        job_id=uuid4(),
        runs=[
            ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector),
            ScoringRun(run_index=1, extraction_id=uuid4(), vector=vector),
        ],
        mean_vector=vector,
        s_tech=0.90,
        sigma=0.0,
        breakdown=[
            DimensionScore(dimension=dimension, score=0.9, weight=0.25, rationale="evidence")
            for dimension in ScoreDimension
        ],
        flags=[],
        recommendation=Recommendation.AUTO_SCHEDULE,
    )


def build() -> World:
    audit = AuditChain()
    applications = ApplicationStore()
    evaluations = EvaluationService(audit=audit, applications=applications)
    approvals = ApprovalEngine(ApprovalStore(), audit=audit)
    communications = CommunicationService(
        evaluations=evaluations, audit=audit, applications=applications
    )
    offers = OfferService(
        evaluations=evaluations,
        communications=communications,
        audit=audit,
        approvals=approvals,
        applications=applications,
    )
    record, _ = applications.submit(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )
    evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(record.candidate_id),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )
    return World(
        audit=audit,
        applications=applications,
        evaluations=evaluations,
        approvals=approvals,
        communications=communications,
        offers=offers,
        application_id=record.id,
        candidate_id=record.candidate_id,
    )


def terms(**overrides: object) -> OfferTerms:
    base: dict[str, object] = {
        "position_title": "Backend Engineer",
        "employment_type": ContractType.PKWTT,
        "start_date": START,
        "probation_months": 3,
        "salary_amount": 25_000_000.0,
        "salary_currency": "IDR",
    }
    base.update(overrides)
    return OfferTerms(**base)  # type: ignore[arg-type]


def approved_offer(world: World) -> UUID:
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))
    world.offers.submit(offer.id, actor=ActorRef.legacy("hr-admin"))
    world.offers.decide(offer.id, decision="approve", actor=ActorRef.legacy("hr-admin"))
    return offer.id


# --- refused operations ---------------------------------------------------------------


def test_offers_require_a_named_human() -> None:
    world = build()
    with pytest.raises(OfferError, match="named human"):
        world.offers.create(world.application_id, terms(), actor=ActorRef.agent("hr_bot"))


def test_create_requires_an_evaluated_application() -> None:
    world = build()
    with pytest.raises(RecruitingError, match="no evaluation"):
        world.offers.create(uuid4(), terms(), actor=ActorRef.legacy("hr-admin"))


def test_unknown_offer_is_refused() -> None:
    world = build()
    with pytest.raises(OfferError, match="unknown offer"):
        world.offers.get(uuid4())


def test_only_drafts_can_be_revised() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))
    world.offers.submit(offer.id, actor=ActorRef.legacy("hr-admin"))

    with pytest.raises(OfferError, match="only draft offers can be revised"):
        world.offers.revise(
            offer.id, terms(salary_amount=30_000_000.0), actor=ActorRef.legacy("hr-admin")
        )


def test_only_drafts_can_be_submitted() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))
    world.offers.submit(offer.id, actor=ActorRef.legacy("hr-admin"))

    with pytest.raises(OfferError, match="only a draft can be submitted"):
        world.offers.submit(offer.id, actor=ActorRef.legacy("hr-admin"))


def test_approval_requires_a_pending_offer() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))

    with pytest.raises(OfferError, match="only a pending offer can be approved"):
        world.offers.decide(offer.id, decision="approve", actor=ActorRef.legacy("hr-admin"))


def test_withdrawal_requires_a_reason() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))
    world.offers.submit(offer.id, actor=ActorRef.legacy("hr-admin"))

    with pytest.raises(OfferError, match="reason is required"):
        world.offers.decide(offer.id, decision="withdraw", actor=ActorRef.legacy("hr-admin"))


def test_approve_refuses_when_the_linked_approval_was_rejected() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))
    world.offers.submit(offer.id, actor=ActorRef.legacy("hr-admin"))
    approval = world.approvals.find_by_subject(ApprovalSubject.OFFER, str(offer.id))
    assert approval is not None
    world.approvals.decide(
        approval.id, actor=ActorRef.legacy("lead-1"), approve=False, reason="budget"
    )

    with pytest.raises(OfferError, match="was rejected"):
        world.offers.decide(offer.id, decision="approve", actor=ActorRef.legacy("hr-admin"))


def test_message_requires_an_approved_offer() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))

    with pytest.raises(OfferError, match="only an approved offer can be sent"):
        world.offers.queue_message(offer.id, actor=ActorRef.legacy("hr-admin"))


def test_acceptance_requires_an_approved_offer() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))

    with pytest.raises(OfferError, match="acceptance is recorded on approved offers"):
        world.offers.record_acceptance(offer.id, actor=ActorRef.legacy("hr-admin"), accepted=True)


def test_decline_requires_a_reason() -> None:
    world = build()
    offer_id = approved_offer(world)

    with pytest.raises(OfferError, match="reason is required"):
        world.offers.record_acceptance(offer_id, actor=ActorRef.legacy("hr-admin"), accepted=False)


def test_agents_cannot_record_acceptance() -> None:
    world = build()
    offer_id = approved_offer(world)

    with pytest.raises(OfferError, match="named human"):
        world.offers.record_acceptance(offer_id, actor=ActorRef.agent("hr_bot"), accepted=True)


def test_terminal_offers_cannot_be_decided_again() -> None:
    world = build()
    offer_id = approved_offer(world)
    world.offers.record_acceptance(offer_id, actor=ActorRef.legacy("hr-admin"), accepted=True)

    with pytest.raises(OfferError, match="cannot be decided again"):
        world.offers.decide(
            offer_id, decision="withdraw", actor=ActorRef.legacy("hr-admin"), reason="changed"
        )


# --- allowed flows --------------------------------------------------------------------


def test_create_records_the_first_revision_and_audit() -> None:
    world = build()
    offer = world.offers.create(
        world.application_id, terms(), actor=ActorRef.legacy("hr-admin"), note="initial"
    )

    assert offer.status is OfferStatus.DRAFT
    assert [item.revision_index for item in offer.revisions] == [1]
    assert offer.revisions[0].offer_id == offer.id
    actions = [entry.action for entry in world.audit.entries]
    assert "offer.created" in actions
    assert world.audit.verify() == -1
    assert [item.id for item in world.offers.list_all(application_id=world.application_id)] == [
        offer.id
    ]


def test_revisions_are_append_only() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))
    updated = world.offers.revise(
        offer.id,
        terms(salary_amount=27_500_000.0),
        actor=ActorRef.legacy("hr-admin"),
        note="negotiated",
    )
    updated = world.offers.revise(
        offer.id, terms(salary_amount=28_000_000.0), actor=ActorRef.legacy("hr-admin"), note="final"
    )

    assert [item.revision_index for item in updated.revisions] == [1, 2, 3]
    assert updated.revisions[0].terms.salary_amount == 25_000_000.0
    assert updated.revisions[-1].terms.salary_amount == 28_000_000.0
    assert world.audit.verify() == -1


def test_submit_creates_the_approval_and_approve_signs_it() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))
    pending = world.offers.submit(offer.id, actor=ActorRef.legacy("hr-admin"))

    approval = world.approvals.find_by_subject(ApprovalSubject.OFFER, str(offer.id))
    assert pending.status is OfferStatus.PENDING_APPROVAL
    assert approval is not None
    assert approval.status is ApprovalStatus.PENDING
    assert approval.assignee_role is ApproverRole.HR_ADMIN

    approved = world.offers.decide(offer.id, decision="approve", actor=ActorRef.legacy("hr-admin"))

    assert approved.status is OfferStatus.APPROVED
    assert approved.decided_by == "hr-admin"
    assert approved.decided_at is not None
    final = world.approvals.find_by_subject(ApprovalSubject.OFFER, str(offer.id))
    assert final is not None
    assert final.status is ApprovalStatus.APPROVED
    actions = [entry.action for entry in world.audit.entries]
    assert "offer.approved" in actions
    assert world.audit.verify() == -1


def test_withdrawal_records_and_withdraws_the_approval() -> None:
    world = build()
    offer = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))
    world.offers.submit(offer.id, actor=ActorRef.legacy("hr-admin"))

    withdrawn = world.offers.decide(
        offer.id, decision="withdraw", actor=ActorRef.legacy("hr-admin"), reason="headcount frozen"
    )

    assert withdrawn.status is OfferStatus.WITHDRAWN
    approval = world.approvals.find_by_subject(ApprovalSubject.OFFER, str(offer.id))
    assert approval is not None
    assert approval.status is ApprovalStatus.WITHDRAWN
    assert world.audit.verify() == -1


def test_queue_message_composes_from_terms_and_queues_the_communication() -> None:
    world = build()
    offer_id = approved_offer(world)

    queued = world.offers.queue_message(offer_id, actor=ActorRef.legacy("hr-admin"))

    assert queued.status is OfferStatus.QUEUED
    assert queued.queued_at is not None
    messages = world.communications.list_for(world.candidate_id)
    assert len(messages) == 1
    assert messages[0].kind is CommunicationKind.OFFER
    assert messages[0].status is CommunicationStatus.QUEUED
    assert "Backend Engineer" in messages[0].body
    assert "IDR" in messages[0].body
    assert world.audit.verify() == -1

    with pytest.raises(OfferError, match="already queued"):
        world.offers.queue_message(offer_id, actor=ActorRef.legacy("hr-admin"))


def test_queue_message_accepts_a_human_edited_body() -> None:
    world = build()
    offer_id = approved_offer(world)

    world.offers.queue_message(
        offer_id, actor=ActorRef.legacy("hr-admin"), body="A personal note from the CEO."
    )

    messages = world.communications.list_for(world.candidate_id)
    assert messages[0].body == "A personal note from the CEO."


def test_acceptance_is_recorded_with_a_timeline_note() -> None:
    world = build()
    offer_id = approved_offer(world)
    world.offers.queue_message(offer_id, actor=ActorRef.legacy("hr-admin"))

    accepted = world.offers.record_acceptance(
        offer_id, actor=ActorRef.legacy("hr-admin"), accepted=True
    )

    assert accepted.status is OfferStatus.ACCEPTED
    assert accepted.accepted_at is not None
    application = world.applications.get(world.application_id)
    assert application is not None
    assert application.timeline[-1][1] == "offer.accepted"
    assert world.audit.verify() == -1


def test_decline_records_the_reason() -> None:
    world = build()
    offer_id = approved_offer(world)

    declined = world.offers.record_acceptance(
        offer_id, actor=ActorRef.legacy("hr-admin"), accepted=False, reason="accepted another offer"
    )

    assert declined.status is OfferStatus.DECLINED
    assert declined.declined_at is not None
    assert declined.decline_reason == "accepted another offer"
    application = world.applications.get(world.application_id)
    assert application is not None
    assert application.timeline[-1][1] == "offer.declined"


def test_expired_offers_do_not_apply_to_accepted_records() -> None:
    world = build()
    expiring = world.offers.create(
        world.application_id,
        terms(expires_at=NOW - timedelta(hours=1)),
        actor=ActorRef.legacy("hr-admin"),
    )
    world.offers.submit(expiring.id, actor=ActorRef.legacy("hr-admin"))
    accepted = world.offers.create(world.application_id, terms(), actor=ActorRef.legacy("hr-admin"))
    world.offers.submit(accepted.id, actor=ActorRef.legacy("hr-admin"))
    world.offers.decide(accepted.id, decision="approve", actor=ActorRef.legacy("hr-admin"))
    world.offers.record_acceptance(accepted.id, actor=ActorRef.legacy("hr-admin"), accepted=True)

    expired = world.offers.expire_overdue(now=NOW, actor=ActorRef.system("offer-expiry"))

    assert [item.id for item in expired] == [expiring.id]
    assert world.offers.get(expiring.id).status is OfferStatus.EXPIRED
    assert world.offers.get(accepted.id).status is OfferStatus.ACCEPTED
    actions = [entry.action for entry in world.audit.entries]
    assert "offer.expired" in actions
    assert world.audit.verify() == -1


def test_compose_offer_body_is_deterministic_and_localized() -> None:
    english = compose_offer_body(terms(), language="en")
    indonesian = compose_offer_body(terms(), language="id")

    assert "Backend Engineer" in english
    assert "IDR 25,000,000.00" in english
    assert "Kompensasi" in indonesian
    assert english != indonesian
