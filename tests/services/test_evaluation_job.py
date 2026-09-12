"""Evaluation job handler: status transitions, audits, failure propagation."""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from hr_agents.models import (
    CandidateProfile,
    DimensionScore,
    PolicyDecision,
    PolicyEvaluation,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
)
from hr_agents.providers.queue import QueueMessage
from hr_agents.services.audit import AuditChain
from hr_agents.services.evaluation_job import (
    EVALUATION_TOPIC,
    EvaluationJobHandler,
    evaluation_payload,
)
from hr_agents.services.ingestion import (
    ApplicationRecord,
    ApplicationStatus,
    ApplicationStore,
    SubmissionInput,
)
from hr_agents.services.pipeline import ApplicationPipeline, PipelineResult
from hr_agents.services.recruiting import EvaluationService, JobService


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


def _setup() -> tuple[
    AuditChain,
    ApplicationRecord,
    ApplicationStore,
    EvaluationService,
    JobService,
    TechnicalEvaluation,
]:
    audit = AuditChain()
    applications = ApplicationStore()
    jobs = JobService(audit=audit)
    evaluations = EvaluationService(audit=audit, applications=applications)
    job = jobs.create(title="Backend Engineer", created_by="hr-admin")
    record, _ = applications.submit(
        SubmissionInput(
            job_id=job.id,
            source_channel="email",
            consent_granted=True,
            candidate_name="Budi Santoso",
        )
    )
    return audit, record, applications, evaluations, jobs, _evaluation(record.candidate_id, job.id)


def _message(record: ApplicationRecord) -> QueueMessage:
    return QueueMessage(
        topic=EVALUATION_TOPIC,
        payload=evaluation_payload(
            application_id=record.id,
            job_id=record.job_id,
            resume_text="Backend engineer with 6 years.",
            candidate_name="Budi Santoso",
        ),
    )


def _pipeline(result: PipelineResult | Exception) -> ApplicationPipeline:
    pipeline = MagicMock(spec=ApplicationPipeline)
    process = (
        AsyncMock(return_value=result)
        if not isinstance(result, Exception)
        else AsyncMock(side_effect=result)
    )
    pipeline.process = process
    return pipeline


def _result(evaluation: TechnicalEvaluation) -> PipelineResult:
    return PipelineResult(
        profile=CandidateProfile(full_name="Budi Santoso"),
        evaluation=evaluation,
        policy=PolicyEvaluation(decision=PolicyDecision.AUTO_SCHEDULE),
        recommendation=Recommendation.AUTO_SCHEDULE,
    )


async def test_handler_processes_and_registers() -> None:
    audit, record, applications, evaluations, jobs, evaluation = _setup()
    handler = EvaluationJobHandler(
        pipeline=_pipeline(_result(evaluation)),
        applications=applications,
        evaluations=evaluations,
        jobs=jobs,
        audit=audit,
    )

    await handler(_message(record))

    reloaded = applications.get(record.id)
    assert reloaded is not None
    assert reloaded.status is ApplicationStatus.EVALUATED
    assert evaluations.get_by_application(record.id).evaluation.id == evaluation.id
    actions = [entry.action for entry in audit.entries]
    assert "worker.processing" in actions
    assert "worker.completed" in actions
    assert audit.verify() == -1


async def test_handler_failure_is_audited_and_propagated() -> None:
    audit, record, applications, evaluations, jobs, _ = _setup()
    handler = EvaluationJobHandler(
        pipeline=_pipeline(RuntimeError("model unavailable")),
        applications=applications,
        evaluations=evaluations,
        jobs=jobs,
        audit=audit,
    )

    with pytest.raises(RuntimeError):
        await handler(_message(record))

    reloaded = applications.get(record.id)
    assert reloaded is not None
    assert reloaded.status is ApplicationStatus.PROCESSING
    actions = [entry.action for entry in audit.entries]
    assert "worker.failed" in actions
    assert "worker.completed" not in actions


async def test_handler_rejects_unknown_application() -> None:
    audit, record, _, evaluations, jobs, evaluation = _setup()
    handler = EvaluationJobHandler(
        pipeline=_pipeline(_result(evaluation)),
        applications=ApplicationStore(),
        evaluations=evaluations,
        jobs=jobs,
        audit=audit,
    )

    with pytest.raises(ValueError):
        await handler(_message(record))
