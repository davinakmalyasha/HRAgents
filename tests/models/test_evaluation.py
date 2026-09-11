from uuid import uuid4

import pytest
from pydantic import ValidationError

from hr_agents.models import (
    DEFAULT_DIMENSION_WEIGHTS,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    aggregate_runs,
)


def vector(value: float) -> ScoreVector:
    return ScoreVector(
        technical_depth=value,
        stack_alignment=value,
        systems_literacy=value,
        verifiable_certifications=value,
    )


def make_run(index: int, value: float) -> ScoringRun:
    return ScoringRun(run_index=index, extraction_id=uuid4(), vector=vector(value))


def test_score_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        vector(1.5)
    with pytest.raises(ValidationError):
        vector(-0.1)


def test_identical_runs_have_zero_sigma() -> None:
    runs = [make_run(0, 0.8), make_run(1, 0.8), make_run(2, 0.8)]
    mean_vector, dimension_stddev, s_tech, sigma = aggregate_runs(runs)

    assert s_tech == pytest.approx(0.8)
    assert sigma == pytest.approx(0.0)
    assert mean_vector.technical_depth == pytest.approx(0.8)
    assert all(value == pytest.approx(0.0) for value in dimension_stddev.values())


def test_sigma_measures_run_disagreement() -> None:
    runs = [make_run(0, 0.9), make_run(1, 0.9), make_run(2, 0.7)]
    _, _, s_tech, sigma = aggregate_runs(runs)

    # s_tech is the mean of the per-run weighted scores
    assert s_tech == pytest.approx((0.9 + 0.9 + 0.7) / 3)
    # population stddev of [0.9, 0.9, 0.7]
    assert sigma == pytest.approx(0.094281, rel=1e-4)


def test_custom_weights_change_s_tech() -> None:
    runs = [
        ScoringRun(
            run_index=0,
            extraction_id=uuid4(),
            vector=ScoreVector(
                technical_depth=1.0,
                stack_alignment=0.0,
                systems_literacy=0.0,
                verifiable_certifications=0.0,
            ),
        )
    ]
    tech_only = {ScoreDimension.TECHNICAL_DEPTH: 1.0}
    _, _, s_tech, _ = aggregate_runs(runs, weights=tech_only)
    assert s_tech == pytest.approx(1.0)


def test_default_weights_sum_to_one() -> None:
    assert sum(DEFAULT_DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)


def test_weighted_mean_requires_positive_weight() -> None:
    with pytest.raises(ValueError, match="positive dimension weight"):
        vector(0.5).weighted_mean({ScoreDimension.TECHNICAL_DEPTH: 0.0})


def test_aggregate_requires_runs() -> None:
    with pytest.raises(ValueError, match="at least one scoring run"):
        aggregate_runs([])
