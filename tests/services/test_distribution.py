"""Per-job score distributions read the real evaluation path, not fixtures."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from hr_agents.models import (
    DimensionScore,
    EvaluationFlag,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
    utc_now,
)
from hr_agents.services.distribution import ScoreDistributionService
from hr_agents.services.recruiting import EvaluationRecord, EvaluationService


def evaluation(
    score: float,
    *,
    job_id: UUID | None = None,
    recommendation: Recommendation | None = None,
    flagged: bool = False,
) -> TechnicalEvaluation:
    vector = ScoreVector(
        technical_depth=score,
        stack_alignment=score,
        systems_literacy=score,
        verifiable_certifications=score,
    )
    return TechnicalEvaluation(
        candidate_id=uuid4(),
        job_id=job_id,
        runs=[
            ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector),
            ScoringRun(run_index=1, extraction_id=uuid4(), vector=vector),
        ],
        mean_vector=vector,
        s_tech=score,
        sigma=0.0,
        breakdown=[
            DimensionScore(dimension=dimension, score=score, weight=0.25, rationale="evidence")
            for dimension in ScoreDimension
        ],
        flags=[EvaluationFlag.LOW_CONFIDENCE_EXTRACTION] if flagged else [],
        recommendation=recommendation
        or (
            Recommendation.REJECT_REQUIRES_SIGNOFF if score < 0.70 else Recommendation.AUTO_SCHEDULE
        ),
    )


def register(
    service: EvaluationService,
    *,
    score: float,
    job_title: str,
    job_id: UUID | None = None,
    recommendation: Recommendation | None = None,
    flagged: bool = False,
) -> EvaluationRecord:
    return service.register(
        application_id=uuid4(),
        evaluation=evaluation(
            score,
            job_id=job_id if job_id is not None else uuid4(),
            recommendation=recommendation,
            flagged=flagged,
        ),
        candidate_name="Budi Santoso",
        job_title=job_title,
    )


def test_groups_by_job_and_bins_the_weighted_total() -> None:
    evaluations = EvaluationService()
    backend = uuid4()
    register(evaluations, score=0.90, job_title="Backend Engineer", job_id=backend)
    register(evaluations, score=0.68, job_title="Backend Engineer", job_id=backend)
    register(evaluations, score=0.71, job_title="Finance Analyst", job_id=uuid4())

    report = ScoreDistributionService(evaluations).report(days=90)

    assert report.evaluations == 3
    assert [job.job_title for job in report.jobs] == ["Backend Engineer", "Finance Analyst"]
    backend_report = report.jobs[0]
    assert backend_report.evaluations == 2
    assert backend_report.mean == 0.79
    assert backend_report.minimum == 0.68
    assert backend_report.maximum == 0.90
    assert [item.count for item in backend_report.bins] == [0, 0, 0, 1, 1]
    assert backend_report.recommendations == {
        "auto_schedule": 1,
        "reject_requires_signoff": 1,
    }
    assert backend_report.requires_human == 1


def test_excludes_records_outside_the_window_and_says_what_it_cannot_measure() -> None:
    evaluations = EvaluationService()
    old = register(evaluations, score=0.90, job_title="Backend Engineer")
    old.registered_at = utc_now() - timedelta(days=200)
    register(evaluations, score=0.80, job_title="Backend Engineer")

    report = ScoreDistributionService(evaluations).report(days=90)

    assert report.evaluations == 1
    assert "Protected attributes are never collected" in report.note
    assert "demographic parity" in report.note


def test_counts_flags_and_can_truncate_the_sample() -> None:
    evaluations = EvaluationService()
    backend = uuid4()
    register(evaluations, score=0.90, job_title="Backend Engineer", job_id=backend, flagged=True)
    register(evaluations, score=0.80, job_title="Backend Engineer", job_id=backend)

    service = ScoreDistributionService(evaluations)
    full = service.report(days=90)
    assert full.jobs[0].flagged == 1
    assert full.truncated is False

    clipped = service.report(days=90, limit=1)
    assert clipped.evaluations == 1
    assert clipped.truncated is True
