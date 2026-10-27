"""Per-job score-distribution monitoring over registered evaluations.

This is the monitoring half of the fairness story. The counterfactual harness
(`services/fairness.py`) proves invariance on synthetic pairs; this reads the
real scoring path — evaluations the pipeline actually registered — and shows
whether one job's scores, routing or flags drift.

It is deliberately not a demographic parity metric: HRAgents does not collect
or score protected attributes, so the only honest distribution it can show is
by job, recommendation, flag and score band. Per-job monitoring catches a
weight change landing on one family, extraction drift, and an unusual share of
manual routing; it cannot and does not claim to measure bias by group.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from hr_agents.models import (
    JobScoreDistribution,
    Recommendation,
    ScoreBin,
    ScoreDistributionReport,
    utc_now,
)
from hr_agents.services.recruiting import EvaluationRecord, EvaluationService

BINS = 5
DEFAULT_LIMIT = 2000

NOTE = (
    "Protected attributes are never collected or scored. This report monitors "
    "per-job score distributions, routing and flags — not demographic parity."
)


def _bin_index(score: float) -> int:
    return min(int(max(score, 0.0) * BINS), BINS - 1)


def _distribution(
    *,
    job_id: UUID | None,
    job_title: str,
    records: list[EvaluationRecord],
) -> JobScoreDistribution:
    totals = [record.evaluation.s_tech for record in records]
    counts = [0] * BINS
    recommendations: dict[str, int] = defaultdict(int)
    flagged = 0
    for record in records:
        counts[_bin_index(record.evaluation.s_tech)] += 1
        recommendations[record.evaluation.recommendation.value] += 1
        flagged += 1 if record.evaluation.flags else 0
    return JobScoreDistribution(
        job_id=job_id,
        job_title=job_title,
        evaluations=len(records),
        mean=round(sum(totals) / len(totals), 4),
        minimum=round(min(totals), 4),
        maximum=round(max(totals), 4),
        bins=[
            ScoreBin(low=index / BINS, high=(index + 1) / BINS, count=counts[index])
            for index in range(BINS)
        ],
        recommendations=dict(sorted(recommendations.items())),
        requires_human=sum(
            recommendations[value.value]
            for value in (
                Recommendation.HUMAN_REVIEW,
                Recommendation.REJECT_REQUIRES_SIGNOFF,
            )
        ),
        flagged=flagged,
    )


class ScoreDistributionService:
    """Builds the report on demand; the evaluation service supplies the rows."""

    def __init__(self, evaluations: EvaluationService) -> None:
        self._evaluations = evaluations

    def report(
        self,
        *,
        days: int = 90,
        limit: int = DEFAULT_LIMIT,
        now: datetime | None = None,
    ) -> ScoreDistributionReport:
        until = now if now is not None else utc_now()
        since = until - timedelta(days=days)
        records = [
            record
            for record in self._evaluations.list_all()
            if since <= record.registered_at <= until
        ]
        records.sort(key=lambda item: (item.registered_at, str(item.evaluation.id)), reverse=True)
        truncated = len(records) > limit
        sampled = records[:limit]

        grouped: dict[tuple[UUID | None, str], list[EvaluationRecord]] = defaultdict(list)
        for record in sampled:
            grouped[(record.job_id, record.job_title)].append(record)

        jobs = [
            _distribution(job_id=job_id, job_title=title, records=group)
            for (job_id, title), group in grouped.items()
        ]
        jobs.sort(key=lambda item: (-item.evaluations, item.job_title))
        return ScoreDistributionReport(
            since=since,
            until=until,
            evaluations=len(sampled),
            truncated=truncated,
            jobs=jobs,
            note=NOTE,
        )
