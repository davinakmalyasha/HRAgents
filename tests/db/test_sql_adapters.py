"""Adapter tests for durable stores, running on in-memory SQLite.

The adapters use plain SQLAlchemy so the same code path is exercised here and
against PostgreSQL in CI (see the ``postgres`` marker).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.application import DbApplicationStore
from hr_agents.db.audit import DbAuditChain
from hr_agents.db.base import Base
from hr_agents.db.recruiting import (
    DbDocumentService,
    DbEvaluationService,
    DbJobService,
    DbSchedulingService,
)
from hr_agents.models import (
    ActorType,
    AuditActor,
    DimensionScore,
    EvaluationFlag,
    FeedbackReport,
    JobSpecification,
    JobStatus,
    PolicyDecision,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    Seniority,
    TechnicalEvaluation,
    TimeSlot,
)
from hr_agents.services.ingestion import (
    ApplicationRecord,
    ApplicationStatus,
    SubmissionConflictError,
    SubmissionInput,
)
from hr_agents.services.recruiting import RecruitingError


def _submission(**overrides: object) -> SubmissionInput:
    defaults: dict[str, object] = {
        "job_id": uuid4(),
        "source_channel": "email",
        "consent_granted": True,
        "candidate_name": "Sari Dewi",
        "candidate_emails": ["sari@example.com"],
    }
    defaults.update(overrides)
    return SubmissionInput(**defaults)  # type: ignore[arg-type]


def _actor(actor_id: str = "hr-admin") -> AuditActor:
    return AuditActor(actor_type=ActorType.HUMAN, actor_id=actor_id)


def _seed_job(factory: sessionmaker[Session]) -> UUID:
    """Applications carry a job FK that Postgres enforces; create a real job."""
    return (
        DbJobService(session_factory=factory, audit=DbAuditChain(factory))
        .create(title="Backend Engineer", created_by="hr-admin")
        .id
    )


def test_metadata_registers_persistence_tables() -> None:
    assert {
        "candidate_documents",
        "evaluation_overrides",
        "feedback_reports",
        "scheduling_availability",
    } <= set(Base.metadata.tables)


def test_audit_chain_persists_and_verifies(factory: sessionmaker[Session]) -> None:
    chain = DbAuditChain(factory)
    first = chain.append(
        actor=_actor(),
        action="employee.created",
        subject_type="employee",
        subject_id="emp-1",
        payload={"name": "Sari"},
    )
    second = chain.append_system(
        action="employee.updated",
        subject_type="employee",
        subject_id="emp-1",
    )

    assert chain.verify() == -1
    assert len(chain.entries) == 2
    assert chain.last_hash == second.entry_hash
    assert first.prev_hash is None
    assert second.prev_hash == first.entry_hash

    reopened = DbAuditChain(factory)
    assert reopened.verify() == -1
    assert [entry.seq for entry in reopened.entries] == [0, 1]


def test_audit_chain_detects_tampering(factory: sessionmaker[Session]) -> None:
    chain = DbAuditChain(factory)
    chain.append(actor=_actor(), action="a", subject_type="x", subject_id="1")
    chain.append(actor=_actor(), action="b", subject_type="x", subject_id="1")

    with factory() as session:
        session.execute(
            update(t.AuditLog).where(t.AuditLog.seq == 1).values(payload={"tampered": True})
        )
        session.commit()

    assert DbAuditChain(factory).verify() == 1


def test_application_submit_is_idempotent(factory: sessionmaker[Session]) -> None:
    store = DbApplicationStore(factory)
    submission = _submission(job_id=_seed_job(factory))

    record, created = store.submit(submission, idempotency_key="key-1")
    assert created is True
    assert record.status is ApplicationStatus.QUEUED

    replay, created_again = store.submit(submission, idempotency_key="key-1")
    assert created_again is False
    assert replay.id == record.id
    assert store.get(record.id) is not None

    with pytest.raises(SubmissionConflictError):
        store.submit(
            _submission(job_id=submission.job_id, candidate_name="Budi"),
            idempotency_key="key-1",
        )


def test_application_status_and_timeline_persist(factory: sessionmaker[Session]) -> None:
    store = DbApplicationStore(factory)
    record, _ = store.submit(_submission(job_id=_seed_job(factory)))

    updated = store.set_status(record.id, ApplicationStatus.PROCESSING, event="worker.claimed")
    assert updated is not None
    assert updated.status is ApplicationStatus.PROCESSING

    reloaded = store.get(record.id)
    assert reloaded is not None
    assert reloaded.status is ApplicationStatus.PROCESSING
    events = [event for _, event in reloaded.timeline]
    assert events == ["application.received", "worker.claimed"]


def test_application_scoring_save_round_trip(factory: sessionmaker[Session]) -> None:
    store = DbApplicationStore(factory)
    record, _ = store.submit(_submission(job_id=_seed_job(factory)))

    record.s_tech = 0.91
    record.sigma = 0.02
    record.recommendation = Recommendation.AUTO_SCHEDULE
    record.status = ApplicationStatus.EVALUATED
    record.note("application.evaluated.evaluated")
    record.refresh_priority()
    store.save(record)

    reloaded = store.get(record.id)
    assert reloaded is not None
    assert reloaded.s_tech == pytest.approx(0.91)
    assert reloaded.sigma == pytest.approx(0.02)
    assert reloaded.recommendation is Recommendation.AUTO_SCHEDULE
    assert reloaded.status is ApplicationStatus.EVALUATED
    assert reloaded.priority_score > 0


def test_application_lists_rank_by_priority(factory: sessionmaker[Session]) -> None:
    store = DbApplicationStore(factory)
    job_id = _seed_job(factory)
    low, _ = store.submit(_submission(job_id=job_id, candidate_name="Low"))
    high, _ = store.submit(_submission(job_id=job_id, candidate_name="High"))

    high.s_tech = 0.95
    high.refresh_priority()
    store.save(high)
    low.s_tech = 0.30
    low.refresh_priority()
    store.save(low)

    ranked = store.list_for_job(job_id)
    assert [record.id for record in ranked] == [high.id, low.id]
    assert [record.id for record in store.iter_all()] == [low.id, high.id]

    found = store.find_by_candidate(high.candidate_id)
    assert [record.id for record in found] == [high.id]

    with factory() as session:
        candidate = session.get(t.Candidate, high.candidate_id)
        assert candidate is not None
        assert candidate.full_name == "High"
        assert candidate.primary_email == "sari@example.com"
        applications = session.execute(select(t.Application)).scalars().all()
        assert len(applications) == 2


# --- recruitment adapters -------------------------------------------------------


def make_evaluation(
    *,
    candidate_id: UUID,
    job_id: UUID,
    s_tech: float = 0.90,
    sigma: float = 0.0,
    flags: list[EvaluationFlag] | None = None,
) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=s_tech,
        stack_alignment=s_tech,
        systems_literacy=s_tech,
        verifiable_certifications=s_tech,
    )
    return TechnicalEvaluation(
        candidate_id=candidate_id,
        job_id=job_id,
        runs=[ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector)],
        mean_vector=vector,
        s_tech=s_tech,
        sigma=sigma,
        breakdown=[
            DimensionScore(
                dimension=dimension, score=s_tech, weight=0.25, rationale=f"{dimension.value} ok"
            )
            for dimension in ScoreDimension
        ],
        flags=flags or [],
        recommendation=Recommendation.AUTO_SCHEDULE,
    )


def make_slots(count: int) -> list[TimeSlot]:
    base = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
    return [
        TimeSlot(
            start_utc=base + timedelta(hours=index),
            end_utc=base + timedelta(hours=index + 1),
        )
        for index in range(count)
    ]


def _seeded(
    factory: sessionmaker[Session],
) -> tuple[DbAuditChain, JobSpecification, DbApplicationStore, ApplicationRecord]:
    audit = DbAuditChain(factory)
    jobs = DbJobService(session_factory=factory, audit=audit)
    applications = DbApplicationStore(factory)
    job = jobs.create(title="Backend Engineer", created_by="hr-admin")
    record, _ = applications.submit(_submission(job_id=job.id))
    return audit, job, applications, record


def _status(store: DbApplicationStore, application_id: UUID) -> ApplicationStatus:
    record = store.get(application_id)
    assert record is not None
    return record.status


def test_document_adapter_round_trip(factory: sessionmaker[Session]) -> None:
    audit = DbAuditChain(factory)
    documents = DbDocumentService(session_factory=factory, audit=audit)
    content = b"Budi Santoso - backend engineer"
    document = documents.upload(
        filename="cv.txt", kind="cv", content=content, uploaded_by="hr-admin"
    )

    fresh = DbDocumentService(session_factory=factory)
    loaded = fresh.get(document.id)
    assert loaded.sha256 == document.sha256
    assert loaded.content == content
    assert [item.id for item in fresh.list_all()] == [document.id]
    assert audit.verify() == -1

    with pytest.raises(RecruitingError):
        fresh.get(uuid4())


def test_job_adapter_lifecycle(factory: sessionmaker[Session]) -> None:
    audit = DbAuditChain(factory)
    jobs = DbJobService(session_factory=factory, audit=audit)
    weights = {
        ScoreDimension.TECHNICAL_DEPTH: 0.5,
        ScoreDimension.STACK_ALIGNMENT: 0.2,
        ScoreDimension.SYSTEMS_LITERACY: 0.2,
        ScoreDimension.VERIFIABLE_CERTIFICATIONS: 0.1,
    }
    job = jobs.create(
        title="Backend Engineer",
        created_by="hr-admin",
        seniority=Seniority.SENIOR,
        dimension_weights=weights,
    )

    fresh = DbJobService(session_factory=factory)
    loaded = fresh.get(job.id)
    assert loaded.title == "Backend Engineer"
    assert loaded.dimension_weights == weights
    assert [item.id for item in fresh.list_all(status=JobStatus.DRAFT)] == [job.id]

    fresh.transition(job.id, target=JobStatus.OPEN, by="hr-admin")
    fresh.update(job.id, by="hr-admin", title="Senior Backend Engineer")
    updated = fresh.get(job.id)
    assert updated.status is JobStatus.OPEN
    assert updated.title == "Senior Backend Engineer"
    assert updated.seniority is Seniority.SENIOR

    fresh.transition(job.id, target=JobStatus.CLOSED, by="hr-admin")
    with pytest.raises(RecruitingError):
        fresh.update(job.id, by="hr-admin", title="Nope")
    assert audit.verify() == -1


def test_evaluation_adapter_registration_and_overrides(factory: sessionmaker[Session]) -> None:
    audit, job, applications, record = _seeded(factory)
    evaluations = DbEvaluationService(
        session_factory=factory, audit=audit, applications=applications
    )
    evaluation = make_evaluation(candidate_id=record.candidate_id, job_id=job.id)
    registered = evaluations.register(
        application_id=record.id,
        evaluation=evaluation,
        candidate_name="Sari Dewi",
        job_title=job.title,
    )
    assert registered.evaluation.id == evaluation.id
    assert _status(applications, record.id) is ApplicationStatus.EVALUATED

    fresh = DbEvaluationService(
        session_factory=factory, audit=DbAuditChain(factory), applications=applications
    )
    loaded = fresh.get(evaluation.id)
    assert loaded.candidate_name == "Sari Dewi"
    assert loaded.policy.decision is PolicyDecision.AUTO_SCHEDULE
    assert fresh.get_by_application(record.id).evaluation.id == evaluation.id
    assert fresh.get_by_candidate(record.candidate_id).evaluation.id == evaluation.id

    outcome = fresh.record_override(
        evaluation.id,
        reviewer_id="lead-1",
        reviewer_role="engineering_lead",
        override_decision=PolicyDecision.HITL_SOFT_REJECTION,
        reason_code="evidence_insufficient",
        notes="Reviewed together",
    )
    overrides = fresh.list_overrides(evaluation.id)
    assert [item.id for item in overrides] == [outcome.override.id]
    assert _status(applications, record.id) is ApplicationStatus.GATED

    with factory() as session:
        assert session.get(t.EvaluationOverrideRecord, outcome.override.id) is not None


def test_feedback_adapter_stores_agent_report(factory: sessionmaker[Session]) -> None:
    audit, job, applications, record = _seeded(factory)
    evaluations = DbEvaluationService(
        session_factory=factory, audit=audit, applications=applications
    )
    report = FeedbackReport(
        candidate_name="Sari Dewi",
        job_title=job.title,
        language="en",
        summary="Structured evaluation summary.",
        process_note="Generated from evidence.",
        correction_notice="Contact HR for corrections.",
    )
    evaluations.save_feedback(record.candidate_id, report, by="agent:feedback_writer")

    fresh = DbEvaluationService(session_factory=factory, audit=DbAuditChain(factory))
    assert fresh.feedback_for(record.candidate_id).summary == report.summary


def test_scheduling_adapter_availability_and_proposal(factory: sessionmaker[Session]) -> None:
    audit, job, applications, record = _seeded(factory)
    evaluations = DbEvaluationService(
        session_factory=factory, audit=audit, applications=applications
    )
    evaluation = make_evaluation(candidate_id=record.candidate_id, job_id=job.id)
    evaluations.register(
        application_id=record.id,
        evaluation=evaluation,
        candidate_name="Sari Dewi",
        job_title=job.title,
    )

    scheduling = DbSchedulingService(
        evaluations=evaluations,
        session_factory=factory,
        audit=audit,
        applications=applications,
    )
    interviewer = uuid4()
    slots = make_slots(2)
    scheduling.set_availability(interviewer, slots=slots, by="hr-admin")
    assert [slot.start_utc for slot in scheduling.get_availability(interviewer)] == [
        slot.start_utc for slot in slots
    ]

    proposal = scheduling.propose(
        candidate_id=record.candidate_id, job_id=job.id, interviewer_ids=[interviewer]
    )
    assert proposal.payload.auto_scheduled is True
    assert _status(applications, record.id) is ApplicationStatus.SCHEDULED

    fresh = DbSchedulingService(evaluations=evaluations, session_factory=factory)
    assert [item.id for item in fresh.list_all()] == [proposal.id]
    assert fresh.get(proposal.id).payload.slots[0].start_utc == slots[0].start_utc
    assert audit.verify() == -1
