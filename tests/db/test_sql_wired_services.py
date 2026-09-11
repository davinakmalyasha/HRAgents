"""Wired DB-backed services over the shared session factory.

Verifies the composition root: containers built with ``session_factory``
persist through the adapters and a fresh container reads the same state.
"""

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import people_tables as pt
from hr_agents.db.application import DbApplicationStore
from hr_agents.db.audit import DbAuditChain
from hr_agents.models import (
    DimensionScore,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
)
from hr_agents.services.ingestion import ApplicationStatus, SubmissionInput
from hr_agents.services.people import PeopleServices
from hr_agents.services.recruiting import RecruitingServices


def _evaluation(candidate_id: UUID, job_id: UUID) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=0.9,
        stack_alignment=0.9,
        systems_literacy=0.9,
        verifiable_certifications=0.9,
    )
    return TechnicalEvaluation(
        candidate_id=candidate_id,
        job_id=job_id,
        runs=[ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector)],
        mean_vector=vector,
        s_tech=0.9,
        sigma=0.0,
        breakdown=[
            DimensionScore(dimension=dimension, score=0.9, weight=0.25, rationale="ok")
            for dimension in ScoreDimension
        ],
        recommendation=Recommendation.AUTO_SCHEDULE,
    )


def test_recruiting_services_wire_to_db(factory: sessionmaker[Session]) -> None:
    audit = DbAuditChain(factory)
    applications = DbApplicationStore(factory)
    services = RecruitingServices(audit=audit, applications=applications, session_factory=factory)

    job = services.jobs.create(title="Backend Engineer", created_by="hr-admin")
    record, created = applications.submit(
        SubmissionInput(
            job_id=job.id,
            source_channel="email",
            consent_granted=True,
            candidate_name="Sari Dewi",
            candidate_emails=["sari@example.com"],
        )
    )
    assert created is True
    registered = services.evaluations.register(
        application_id=record.id,
        evaluation=_evaluation(record.candidate_id, job.id),
        candidate_name="Sari Dewi",
        job_title=job.title,
    )

    fresh_audit = DbAuditChain(factory)
    fresh = RecruitingServices(
        audit=fresh_audit,
        applications=DbApplicationStore(factory),
        session_factory=factory,
    )
    loaded = fresh.evaluations.get(registered.evaluation.id)
    assert loaded.candidate_name == "Sari Dewi"
    assert fresh.jobs.get(job.id).title == "Backend Engineer"

    reloaded = DbApplicationStore(factory).get(record.id)
    assert reloaded is not None
    assert reloaded.status is ApplicationStatus.EVALUATED
    assert fresh_audit.verify() == -1


def test_people_services_wire_to_db(factory: sessionmaker[Session]) -> None:
    audit = DbAuditChain(factory)
    people = PeopleServices(audit=audit, session_factory=factory)
    employee = people.employees.create(
        full_name="Sari Dewi",
        created_by="hr-admin",
        job_title="Finance Staff",
        hire_date=date.today(),
    )

    fresh = PeopleServices(audit=DbAuditChain(factory), session_factory=factory)
    loaded = fresh.employees.get(employee.id)
    assert loaded is not None
    assert loaded.full_name == "Sari Dewi"
    assert loaded.job_title == "Finance Staff"

    with factory() as session:
        assert session.get(pt.EmployeeRecord, employee.id) is not None
    assert audit.verify() == -1
