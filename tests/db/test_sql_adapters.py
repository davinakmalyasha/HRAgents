"""Adapter tests for durable stores, running on in-memory SQLite.


The adapters use plain SQLAlchemy so the same code path is exercised here and
against PostgreSQL in CI (see the ``postgres`` marker).
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.application import DbApplicationStore
from hr_agents.db.audit import DbAuditChain
from hr_agents.db.base import Base
from hr_agents.db.messaging import (
    DbCandidateDirectory,
    DbReplyStore,
    candidate_directory,
    reply_store,
)
from hr_agents.db.offers import DbOfferService
from hr_agents.db.recruiting import (
    DbCommunicationService,
    DbDocumentService,
    DbEvaluationService,
    DbJobService,
    DbSchedulingService,
)
from hr_agents.identity import ActorRef
from hr_agents.messaging.contacts import InMemoryCandidateDirectory
from hr_agents.messaging.store import ReplyStore, reply_dedup_key
from hr_agents.models import (
    ActorType,
    AuditActor,
    CandidateCommunication,
    CandidateReply,
    Channel,
    CommunicationStatus,
    ContractType,
    DimensionScore,
    EvaluationFlag,
    FeedbackReport,
    JobSpecification,
    JobStatus,
    OfferStatus,
    OfferTerms,
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
        .create(title="Backend Engineer", actor=ActorRef.legacy("hr-admin"))
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
    assert {record.id for record in store.iter_all()} == {low.id, high.id}

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
        runs=[
            ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector),
            ScoringRun(run_index=1, extraction_id=uuid4(), vector=vector),
        ],
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
    job = jobs.create(title="Backend Engineer", actor=ActorRef.legacy("hr-admin"))
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
        filename="cv.txt", kind="cv", content=content, actor=ActorRef.legacy("hr-admin")
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
        actor=ActorRef.legacy("hr-admin"),
        seniority=Seniority.SENIOR,
        dimension_weights=weights,
    )

    fresh = DbJobService(session_factory=factory)
    loaded = fresh.get(job.id)
    assert loaded.title == "Backend Engineer"
    assert loaded.dimension_weights == weights
    assert [item.id for item in fresh.list_all(status=JobStatus.DRAFT)] == [job.id]

    fresh.transition(job.id, target=JobStatus.OPEN, actor=ActorRef.legacy("hr-admin"))
    fresh.update(job.id, actor=ActorRef.legacy("hr-admin"), title="Senior Backend Engineer")
    updated = fresh.get(job.id)
    assert updated.status is JobStatus.OPEN
    assert updated.title == "Senior Backend Engineer"
    assert updated.seniority is Seniority.SENIOR

    fresh.transition(job.id, target=JobStatus.CLOSED, actor=ActorRef.legacy("hr-admin"))
    with pytest.raises(RecruitingError):
        fresh.update(job.id, actor=ActorRef.legacy("hr-admin"), title="Nope")
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
    evaluations.save_feedback(
        record.candidate_id, report, actor=ActorRef.legacy("agent:feedback_writer")
    )

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
    scheduling.set_availability(interviewer, slots=slots, actor=ActorRef.legacy("hr-admin"))
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


def test_communication_adapter_queue_and_sent(factory: sessionmaker[Session]) -> None:
    audit, job, applications, record = _seeded(factory)
    evaluations = DbEvaluationService(
        session_factory=factory, audit=audit, applications=applications
    )
    evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(candidate_id=record.candidate_id, job_id=job.id, s_tech=0.50),
        candidate_name="Sari Dewi",
        job_title=job.title,
    )
    communications = DbCommunicationService(
        evaluations=evaluations, session_factory=factory, audit=audit, applications=applications
    )

    item = communications.queue_rejection(
        record.candidate_id, actor=ActorRef.legacy("hr-admin"), language="id"
    )
    assert item.status is CommunicationStatus.QUEUED
    communications.mark_sent(item.id, actor=ActorRef.legacy("hr-admin"))

    fresh = DbCommunicationService(evaluations=evaluations, session_factory=factory)
    loaded = fresh.list_for(record.candidate_id)
    assert [entry.id for entry in loaded] == [item.id]
    assert loaded[0].body == item.body
    assert loaded[0].language == "id"
    assert loaded[0].status is CommunicationStatus.SENT
    assert loaded[0].sent_at is not None
    assert audit.verify() == -1


def test_communication_adapter_persists_transport_evidence(
    factory: sessionmaker[Session],
) -> None:
    audit, job, applications, record = _seeded(factory)
    evaluations = DbEvaluationService(
        session_factory=factory, audit=audit, applications=applications
    )
    evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(candidate_id=record.candidate_id, job_id=job.id, s_tech=0.50),
        candidate_name="Sari Dewi",
        job_title=job.title,
    )
    communications = DbCommunicationService(
        evaluations=evaluations, session_factory=factory, audit=audit, applications=applications
    )
    item = communications.queue_rejection(
        record.candidate_id, actor=ActorRef.legacy("hr-admin"), to_email="sari@example.com"
    )
    communications.record_dispatch_failure(item.id, provider="email.smtp", error="mailbox down")
    communications.record_dispatch(
        item.id,
        provider="email.smtp",
        recipient="sari@example.com",
        message_id="<outbound-9@example.com>",
    )

    fresh = DbCommunicationService(evaluations=evaluations, session_factory=factory)
    loaded = fresh.get(item.id)
    assert loaded.status is CommunicationStatus.SENT
    assert loaded.recipient == "sari@example.com"
    assert loaded.provider == "email.smtp"
    assert loaded.provider_message_id == "<outbound-9@example.com>"
    assert loaded.send_attempts == 2
    assert loaded.last_error is None
    threaded = fresh.find_by_provider_message_id("<outbound-9@example.com>")
    assert threaded is not None and threaded.id == item.id


def test_reply_store_deduplicates_across_instances(factory: sessionmaker[Session]) -> None:
    _audit, _job, _applications, record = _seeded(factory)
    replies = DbReplyStore(session_factory=factory)
    reply = CandidateReply(
        candidate_id=record.candidate_id,
        sender="sari@example.com",
        subject="Re: Your application",
        body="Terima kasih, saya tertarik.",
        provider="email.imap_poll",
        provider_message_id="<reply-1@example.com>",
        dedup_key=reply_dedup_key(
            provider="email.imap_poll",
            message_id="<reply-1@example.com>",
            sender="sari@example.com",
            subject="Re: Your application",
            body="Terima kasih, saya tertarik.",
        ),
    )

    replies.add(reply)
    fresh = DbReplyStore(session_factory=factory)
    duplicate = fresh.add(reply.model_copy(update={"id": uuid4()}))

    assert duplicate.id == reply.id
    assert [entry.id for entry in fresh.list_for(record.candidate_id)] == [reply.id]


def test_candidate_directory_reads_the_recorded_address(
    factory: sessionmaker[Session],
) -> None:
    _audit, _job, _applications, record = _seeded(factory)
    directory = DbCandidateDirectory(session_factory=factory)

    assert directory.primary_email(record.candidate_id) == "sari@example.com"
    assert directory.candidate_for_email("SARI@example.com") == record.candidate_id
    assert directory.candidate_for_email("stranger@elsewhere.com") is None


def test_filtered_communication_reads_query_instead_of_scanning(
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit, job, applications, record = _seeded(factory)
    evaluations = DbEvaluationService(
        session_factory=factory, audit=audit, applications=applications
    )
    evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(candidate_id=record.candidate_id, job_id=job.id),
        candidate_name="Sari Dewi",
        job_title=job.title,
    )
    other_record, _ = applications.submit(
        SubmissionInput(job_id=job.id, source_channel="api", consent_granted=True)
    )
    evaluations.register(
        application_id=other_record.id,
        evaluation=make_evaluation(candidate_id=other_record.candidate_id, job_id=job.id),
        candidate_name="Budi Santoso",
        job_title=job.title,
    )
    communications = DbCommunicationService(
        evaluations=evaluations, session_factory=factory, audit=audit, applications=applications
    )
    mine = communications.queue_offer(
        record.candidate_id,
        actor=ActorRef.legacy("hr-admin"),
        body="Offer body",
        channel=Channel.EMAIL,
        to_email="sari@example.com",
    )
    theirs = communications.queue_offer(
        other_record.candidate_id,
        actor=ActorRef.legacy("hr-admin"),
        body="Other body",
        channel=Channel.WHATSAPP,
    )
    communications.record_dispatch(
        mine.id,
        provider="email.smtp",
        recipient="sari@example.com",
        message_id="<Outbound-7@Example.com>",
    )

    def no_full_scan() -> Iterator[CandidateCommunication]:
        raise AssertionError("filtered reads must filter in SQL, not scan the table")

    monkeypatch.setattr(communications, "_iter", no_full_scan)

    assert [item.id for item in communications.list_for(record.candidate_id)] == [mine.id]
    assert [item.id for item in communications.list_queued()] == [theirs.id]
    assert [item.id for item in communications.list_queued(channel=Channel.EMAIL)] == []
    assert [item.id for item in communications.list_sent()] == [mine.id]
    threaded = communications.find_by_provider_message_id("<outbound-7@example.com>")
    assert threaded is not None and threaded.id == mine.id
    assert communications.find_by_provider_message_id("<unknown@example.com>") is None


def test_in_memory_messaging_stores_are_used_without_a_database() -> None:
    assert isinstance(candidate_directory(None), InMemoryCandidateDirectory)
    assert isinstance(reply_store(None), ReplyStore)


def test_offer_adapter_records_and_revisions(factory: sessionmaker[Session]) -> None:
    audit, job, applications, record = _seeded(factory)
    evaluations = DbEvaluationService(
        session_factory=factory, audit=audit, applications=applications
    )
    evaluations.register(
        application_id=record.id,
        evaluation=make_evaluation(candidate_id=record.candidate_id, job_id=job.id),
        candidate_name="Sari Dewi",
        job_title=job.title,
    )
    communications = DbCommunicationService(
        evaluations=evaluations, session_factory=factory, audit=audit, applications=applications
    )
    offers = DbOfferService(
        evaluations=evaluations,
        communications=communications,
        session_factory=factory,
        audit=audit,
        applications=applications,
    )
    terms = OfferTerms(
        position_title=job.title,
        employment_type=ContractType.PKWTT,
        start_date=date(2026, 11, 1),
        salary_amount=25_000_000.0,
        salary_currency="IDR",
    )
    created = offers.create(record.id, terms, by="hr-admin")
    revised_terms = terms.model_copy(update={"salary_amount": 27_000_000.0})
    offers.revise(created.id, revised_terms, by="hr-admin", note="negotiated")

    fresh = DbOfferService(
        evaluations=evaluations, communications=communications, session_factory=factory
    )
    loaded = fresh.get(created.id)
    assert loaded.status is OfferStatus.DRAFT
    assert loaded.terms.salary_amount == 27_000_000.0
    assert [item.revision_index for item in loaded.revisions] == [1, 2]
    assert loaded.revisions[0].terms.salary_amount == 25_000_000.0
    assert [item.id for item in fresh.list_all()] == [created.id]
    assert audit.verify() == -1
