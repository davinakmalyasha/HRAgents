"""Adapter tests for durable stores, running on in-memory SQLite.

The adapters use plain SQLAlchemy so the same code path is exercised here and
against PostgreSQL in CI (see the ``postgres`` marker).
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from hr_agents.db import tables as t
from hr_agents.db.application import DbApplicationStore
from hr_agents.db.audit import DbAuditChain
from hr_agents.db.base import Base
from hr_agents.models import ActorType, AuditActor, Recommendation
from hr_agents.services.ingestion import (
    ApplicationStatus,
    SubmissionConflictError,
    SubmissionInput,
)


@pytest.fixture
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False, autoflush=False)
    engine.dispose()


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
    submission = _submission()

    record, created = store.submit(submission, idempotency_key="key-1")
    assert created is True
    assert record.status is ApplicationStatus.QUEUED

    replay, created_again = store.submit(submission, idempotency_key="key-1")
    assert created_again is False
    assert replay.id == record.id
    assert store.get(record.id) is not None

    with pytest.raises(SubmissionConflictError):
        store.submit(_submission(candidate_name="Budi"), idempotency_key="key-1")


def test_application_status_and_timeline_persist(factory: sessionmaker[Session]) -> None:
    store = DbApplicationStore(factory)
    record, _ = store.submit(_submission())

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
    record, _ = store.submit(_submission())

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
    job_id = uuid4()
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
