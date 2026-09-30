"""Scheduling proposal decisions: named humans, approval linkage, supersede chain.

Negative tests first — agents cannot decide, reasons are mandatory for
cancel/reschedule, terminal proposals stay terminal, and a failed reschedule
leaves the original proposal untouched.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from hr_agents.identity import ActorRef
from hr_agents.models import (
    ApprovalStatus,
    ApprovalSubject,
    ApproverRole,
    DimensionScore,
    ProposalStatus,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
    TimeSlot,
    utc_now,
)
from hr_agents.services import ApplicationStore, AuditChain, SubmissionInput
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.ingestion import ApplicationStatus
from hr_agents.services.people_store import ApprovalStore
from hr_agents.services.recruiting import (
    EvaluationService,
    RecruitingError,
    SchedulingProposalRecord,
    SchedulingService,
)

BASE_SLOT = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)


@dataclass
class World:
    audit: AuditChain
    evaluations: EvaluationService
    applications: ApplicationStore
    approvals: ApprovalEngine | None
    scheduling: SchedulingService
    application_id: UUID
    candidate_id: UUID
    interviewer_id: UUID


def make_evaluation(candidate_id: UUID, *, s_tech: float) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=s_tech,
        stack_alignment=s_tech,
        systems_literacy=s_tech,
        verifiable_certifications=s_tech,
    )
    recommendation = Recommendation.AUTO_SCHEDULE if s_tech >= 0.85 else Recommendation.HUMAN_REVIEW
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
        recommendation=recommendation,
    )


def make_slots(count: int) -> list[TimeSlot]:
    return [
        TimeSlot(
            start_utc=BASE_SLOT + timedelta(hours=index),
            end_utc=BASE_SLOT + timedelta(hours=index + 1),
        )
        for index in range(count)
    ]


def build(*, s_tech: float = 0.80, with_engine: bool = True) -> World:
    audit = AuditChain()
    applications = ApplicationStore()
    evaluations = EvaluationService(audit=audit, applications=applications)
    approvals = ApprovalEngine(ApprovalStore(), audit=audit) if with_engine else None
    scheduling = SchedulingService(
        evaluations=evaluations,
        audit=audit,
        applications=applications,
        approvals=approvals,
    )
    record, _ = applications.submit(
        SubmissionInput(job_id=uuid4(), source_channel="api", consent_granted=True)
    )
    evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(record.candidate_id, s_tech=s_tech),
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
    )
    interviewer = uuid4()
    scheduling.set_availability(interviewer, slots=make_slots(3), actor=ActorRef.legacy("hr-admin"))
    return World(
        audit=audit,
        evaluations=evaluations,
        applications=applications,
        approvals=approvals,
        scheduling=scheduling,
        application_id=record.id,
        candidate_id=record.candidate_id,
        interviewer_id=interviewer,
    )


def engine_of(world: World) -> ApprovalEngine:
    assert world.approvals is not None
    return world.approvals


def propose(world: World) -> SchedulingProposalRecord:
    return world.scheduling.propose(
        candidate_id=world.candidate_id,
        job_id=uuid4(),
        interviewer_ids=[world.interviewer_id],
    )


# --- refused decisions ---------------------------------------------------------------


def test_decisions_require_a_named_human() -> None:
    world = build()
    proposal = propose(world)

    with pytest.raises(RecruitingError, match="named human"):
        world.scheduling.decide(
            proposal.id, decision="confirm", actor=ActorRef.legacy("agent:hr_bot")
        )


def test_cancel_and_reschedule_require_a_reason() -> None:
    world = build()
    proposal = propose(world)

    with pytest.raises(RecruitingError, match="reason is required"):
        world.scheduling.decide(proposal.id, decision="cancel", actor=ActorRef.legacy("hr-admin"))
    with pytest.raises(RecruitingError, match="reason is required"):
        world.scheduling.decide(
            proposal.id, decision="reschedule", actor=ActorRef.legacy("hr-admin")
        )


def test_unknown_proposal_is_refused() -> None:
    world = build()

    with pytest.raises(RecruitingError, match="unknown scheduling proposal"):
        world.scheduling.decide(uuid4(), decision="confirm", actor=ActorRef.legacy("hr-admin"))


def test_unknown_decision_is_refused() -> None:
    world = build()
    proposal = propose(world)

    with pytest.raises(RecruitingError, match="unknown decision"):
        world.scheduling.decide(proposal.id, decision="maybe", actor=ActorRef.legacy("hr-admin"))


def test_terminal_proposals_cannot_be_decided_again() -> None:
    world = build()
    proposal = propose(world)
    world.scheduling.decide(
        proposal.id,
        decision="cancel",
        actor=ActorRef.legacy("hr-admin"),
        reason="interviewer unavailable",
    )

    with pytest.raises(RecruitingError, match="cannot be decided again"):
        world.scheduling.decide(proposal.id, decision="confirm", actor=ActorRef.legacy("hr-admin"))
    with pytest.raises(RecruitingError, match="cannot be decided again"):
        world.scheduling.decide(
            proposal.id,
            decision="reschedule",
            actor=ActorRef.legacy("hr-admin"),
            reason="another try",
        )


def test_confirm_refuses_when_the_linked_approval_was_rejected() -> None:
    world = build()
    proposal = propose(world)
    approval = engine_of(world).find_by_subject(ApprovalSubject.SCHEDULING, str(proposal.id))
    assert approval is not None
    engine_of(world).decide(approval.id, decided_by="lead-1", approve=False, reason="no slots")

    with pytest.raises(RecruitingError, match="was rejected"):
        world.scheduling.decide(proposal.id, decision="confirm", actor=ActorRef.legacy("hr-admin"))


def test_reschedule_without_availability_keeps_the_old_proposal() -> None:
    world = build()
    proposal = propose(world)
    world.scheduling.set_availability(
        world.interviewer_id, slots=[], actor=ActorRef.legacy("hr-admin")
    )

    with pytest.raises(RecruitingError, match="no interviewer availability"):
        world.scheduling.decide(
            proposal.id,
            decision="reschedule",
            actor=ActorRef.legacy("hr-admin"),
            reason="times changed",
        )

    assert world.scheduling.get(proposal.id).status is ProposalStatus.PENDING_APPROVAL
    assert [item.id for item in world.scheduling.list_all()] == [proposal.id]


# --- allowed decisions ----------------------------------------------------------------


def test_propose_creates_a_pending_scheduling_approval() -> None:
    world = build()
    proposal = propose(world)

    approval = engine_of(world).find_by_subject(ApprovalSubject.SCHEDULING, str(proposal.id))

    assert proposal.status is ProposalStatus.PENDING_APPROVAL
    assert approval is not None
    assert approval.status is ApprovalStatus.PENDING
    assert approval.assignee_role is ApproverRole.RECRUITER_LEAD
    assert str(world.candidate_id)[:8] in approval.title
    assert approval.payload["proposal_id"] == str(proposal.id)


def test_confirm_decides_the_linked_approval_and_schedules() -> None:
    world = build()
    proposal = propose(world)

    decided, replacement = world.scheduling.decide(
        proposal.id,
        decision="confirm",
        actor=ActorRef.legacy("hr-admin"),
        reason="slots work for the panel",
    )

    assert replacement is None
    assert decided.status is ProposalStatus.CONFIRMED
    assert decided.decided_by == "hr-admin"
    assert decided.decided_at is not None

    approval = engine_of(world).find_by_subject(ApprovalSubject.SCHEDULING, str(proposal.id))
    assert approval is not None
    assert approval.status is ApprovalStatus.APPROVED
    assert approval.decided_by == "hr-admin"

    application = world.applications.get(world.application_id)
    assert application is not None
    assert application.status is ApplicationStatus.SCHEDULED
    assert application.timeline[-1][1] == "scheduling.proposal_confirmed"

    actions = [entry.action for entry in world.audit.entries]
    assert "scheduling.proposal_confirmed" in actions
    assert "approval.approved" in actions
    assert world.audit.verify() == -1


def test_auto_proposals_confirm_idempotently_without_an_approval() -> None:
    world = build(s_tech=0.92)
    proposal = propose(world)
    assert proposal.status is ProposalStatus.AUTO_SCHEDULED
    assert engine_of(world).find_by_subject(ApprovalSubject.SCHEDULING, str(proposal.id)) is None

    confirmed, _ = world.scheduling.decide(
        proposal.id, decision="confirm", actor=ActorRef.legacy("hr-admin")
    )
    again, _ = world.scheduling.decide(
        proposal.id, decision="confirm", actor=ActorRef.legacy("hr-admin")
    )

    assert confirmed.status is ProposalStatus.CONFIRMED
    assert confirmed.decided_by == "hr-admin"
    assert again.status is ProposalStatus.CONFIRMED
    assert again.decided_by == "hr-admin"


def test_confirm_without_an_engine_uses_the_direct_audited_path() -> None:
    world = build(with_engine=False)
    proposal = propose(world)

    decided, _ = world.scheduling.decide(
        proposal.id, decision="confirm", actor=ActorRef.legacy("hr-admin")
    )

    assert decided.status is ProposalStatus.CONFIRMED
    payload = next(
        entry for entry in world.audit.entries if entry.action == "scheduling.proposal_confirmed"
    ).payload
    assert payload["approval"] == "none"


def test_cancel_withdraws_the_linked_approval_and_leaves_the_application() -> None:
    world = build()
    proposal = propose(world)

    cancelled, replacement = world.scheduling.decide(
        proposal.id,
        decision="cancel",
        actor=ActorRef.legacy("hr-admin"),
        reason="interviewer went on leave",
    )

    assert replacement is None
    assert cancelled.status is ProposalStatus.CANCELLED
    approval = engine_of(world).find_by_subject(ApprovalSubject.SCHEDULING, str(proposal.id))
    assert approval is not None
    assert approval.status is ApprovalStatus.WITHDRAWN

    application = world.applications.get(world.application_id)
    assert application is not None
    assert application.status is ApplicationStatus.GATED
    assert world.audit.verify() == -1


def test_reschedule_supersedes_and_links_the_replacement() -> None:
    world = build()
    proposal = propose(world)
    world.scheduling.set_availability(
        world.interviewer_id, slots=make_slots(2), actor=ActorRef.legacy("hr-admin")
    )

    superseded, replacement = world.scheduling.decide(
        proposal.id,
        decision="reschedule",
        actor=ActorRef.legacy("hr-admin"),
        reason="candidate asked for later",
    )

    assert superseded.status is ProposalStatus.SUPERSEDED
    assert replacement is not None
    assert replacement.status is ProposalStatus.PENDING_APPROVAL
    assert replacement.supersedes_id == proposal.id
    assert len(replacement.payload.slots) == 2

    old_approval = engine_of(world).find_by_subject(ApprovalSubject.SCHEDULING, str(proposal.id))
    assert old_approval is not None
    assert old_approval.status is ApprovalStatus.WITHDRAWN
    new_approval = engine_of(world).find_by_subject(ApprovalSubject.SCHEDULING, str(replacement.id))
    assert new_approval is not None
    assert new_approval.status is ApprovalStatus.PENDING

    assert {item.id for item in world.scheduling.list_all()} == {proposal.id, replacement.id}
    payload = next(
        entry for entry in world.audit.entries if entry.action == "scheduling.proposal_superseded"
    ).payload
    assert payload["superseded_by"] == str(replacement.id)
    assert world.audit.verify() == -1


def test_decided_at_uses_utc_now() -> None:
    world = build()
    proposal = propose(world)
    before = utc_now()
    decided, _ = world.scheduling.decide(
        proposal.id, decision="confirm", actor=ActorRef.legacy("hr-admin")
    )
    assert decided.decided_at is not None
    assert decided.decided_at >= before
