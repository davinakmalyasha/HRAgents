import pytest
from pydantic import ValidationError

from hr_agents.models import (
    DEFAULT_DIMENSION_WEIGHTS,
    JobSpecification,
    ScoreDimension,
    Seniority,
)


def test_default_weights_used_when_unspecified() -> None:
    job = JobSpecification(title="Backend Engineer", seniority=Seniority.MID)
    assert job.effective_weights() == DEFAULT_DIMENSION_WEIGHTS


def test_custom_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match=r"must sum to 1\.0"):
        JobSpecification(
            title="AI Engineer",
            dimension_weights={
                ScoreDimension.TECHNICAL_DEPTH: 0.5,
                ScoreDimension.STACK_ALIGNMENT: 0.5,
                ScoreDimension.SYSTEMS_LITERACY: 0.5,
            },
        )


def test_negative_weights_rejected() -> None:
    with pytest.raises(ValidationError, match="non-negative"):
        JobSpecification(
            title="AI Engineer",
            dimension_weights={
                ScoreDimension.TECHNICAL_DEPTH: 1.2,
                ScoreDimension.STACK_ALIGNMENT: -0.2,
            },
        )


def test_custom_weights_round_trip() -> None:
    weights = {
        ScoreDimension.TECHNICAL_DEPTH: 0.5,
        ScoreDimension.STACK_ALIGNMENT: 0.3,
        ScoreDimension.SYSTEMS_LITERACY: 0.15,
        ScoreDimension.VERIFIABLE_CERTIFICATIONS: 0.05,
    }
    job = JobSpecification(title="AI Engineer", dimension_weights=weights)
    assert job.effective_weights() == weights
