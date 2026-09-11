from pathlib import Path
from uuid import uuid4

import pytest
from pydantic_ai.models.test import TestModel

from hr_agents.agents import AgentDeps, AgentRuntime
from hr_agents.agents.feedback_writer import (
    FeedbackResult,
    FeedbackWriter,
    GroundingCode,
    validate_grounding,
)
from hr_agents.models import (
    FeedbackGrowthArea,
    FeedbackReport,
    FeedbackStrength,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
    aggregate_runs,
)
from hr_agents.services.audit import AuditChain
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.tools import ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


def make_evaluation(vector: ScoreVector) -> TechnicalEvaluation:
    runs = [ScoringRun(run_index=index, extraction_id=uuid4(), vector=vector) for index in range(3)]
    mean, stddev, s_tech, sigma = aggregate_runs(runs)
    return TechnicalEvaluation(
        candidate_id=uuid4(),
        runs=runs,
        mean_vector=mean,
        dimension_stddev=stddev,
        s_tech=s_tech,
        sigma=sigma,
        recommendation=Recommendation.HUMAN_REVIEW,
    )


STRONG_ALL = ScoreVector(
    technical_depth=0.9,
    stack_alignment=0.9,
    systems_literacy=0.9,
    verifiable_certifications=0.9,
)
MIXED = ScoreVector(
    technical_depth=0.85,
    stack_alignment=0.8,
    systems_literacy=0.55,
    verifiable_certifications=0.2,
)


def make_report(**overrides: object) -> FeedbackReport:
    defaults: dict[str, object] = {
        "candidate_name": "Budi Santoso",
        "job_title": "Backend Engineer",
        "summary": "Evidence-based review completed.",
        "strengths": [
            FeedbackStrength(
                dimension=ScoreDimension.TECHNICAL_DEPTH, text="Six years of backend work."
            )
        ],
        "growth_areas": [
            FeedbackGrowthArea(
                dimension=ScoreDimension.VERIFIABLE_CERTIFICATIONS,
                text="No verifiable certification was found.",
            )
        ],
        "process_note": "Reviewed across four dimensions and signed off by an engineer.",
        "correction_notice": "Reply to correct any extracted fact.",
    }
    defaults.update(overrides)
    return FeedbackReport(**defaults)  # type: ignore[arg-type]


def test_valid_report_passes_grounding() -> None:
    evaluation = make_evaluation(MIXED)
    violations = validate_grounding(make_report(), evaluation)
    assert violations == []


def test_strength_on_weak_dimension_violation() -> None:
    evaluation = make_evaluation(MIXED)
    report = make_report(
        strengths=[
            FeedbackStrength(
                dimension=ScoreDimension.VERIFIABLE_CERTIFICATIONS,
                text="Strong certifications.",
            )
        ]
    )
    violations = validate_grounding(report, evaluation)
    assert any(violation.code is GroundingCode.STRENGTH_BELOW_THRESHOLD for violation in violations)


def test_growth_on_strong_dimension_violation() -> None:
    evaluation = make_evaluation(STRONG_ALL)
    report = make_report(
        growth_areas=[
            FeedbackGrowthArea(dimension=ScoreDimension.TECHNICAL_DEPTH, text="Needs more depth.")
        ],
        strengths=[
            FeedbackStrength(dimension=ScoreDimension.TECHNICAL_DEPTH, text="Deep experience.")
        ],
    )
    violations = validate_grounding(report, evaluation)
    assert any(violation.code is GroundingCode.GROWTH_ABOVE_THRESHOLD for violation in violations)


def test_duplicate_dimension_violation() -> None:
    evaluation = make_evaluation(STRONG_ALL)
    report = make_report(
        strengths=[
            FeedbackStrength(dimension=ScoreDimension.TECHNICAL_DEPTH, text="One."),
            FeedbackStrength(dimension=ScoreDimension.TECHNICAL_DEPTH, text="Two."),
        ]
    )
    violations = validate_grounding(report, evaluation)
    assert any(violation.code is GroundingCode.DUPLICATE_DIMENSION for violation in violations)


def test_protected_attribute_violation() -> None:
    evaluation = make_evaluation(MIXED)
    report = make_report(summary="Despite marital status, the candidate performed well.")
    violations = validate_grounding(report, evaluation)
    assert any(violation.code is GroundingCode.PROTECTED_ATTRIBUTE for violation in violations)


@pytest.mark.parametrize("term", ["usia", "agama", "nikah", "pregnant", "ethnic"])
def test_protected_terms_indonesian_and_english(term: str) -> None:
    evaluation = make_evaluation(MIXED)
    report = make_report(summary=f"Notes about {term} were considered.")
    violations = validate_grounding(report, evaluation)
    assert any(violation.code is GroundingCode.PROTECTED_ATTRIBUTE for violation in violations)


def test_no_strengths_violation() -> None:
    evaluation = make_evaluation(STRONG_ALL)
    report = make_report(strengths=[])
    violations = validate_grounding(report, evaluation)
    assert any(violation.code is GroundingCode.NO_STRENGTHS for violation in violations)


@pytest.fixture
def skills() -> SkillRegistry:
    return SkillRegistry(load_library(SKILLS_ROOT))


def test_feedback_result_passes_property() -> None:
    result = FeedbackResult(report=make_report())
    assert result.passes_grounding is True


async def test_writer_runs_and_validates(skills: SkillRegistry) -> None:
    runtime = AgentRuntime(TestModel(call_tools=[]))
    writer = FeedbackWriter(runtime, skills=skills)
    evaluation = make_evaluation(STRONG_ALL)

    result = await writer.write(
        evaluation=evaluation,
        candidate_name="Budi Santoso",
        job_title="Backend Engineer",
        deps=AgentDeps(tools=ToolRegistry(audit=AuditChain())),
    )

    # The offline model generates a schema-valid report; grounding is checked
    # deterministically regardless of what the model wrote.
    assert isinstance(result.report, FeedbackReport)
    assert result.report.candidate_name
    assert result.skill_refs
    ref_ids = {ref["skill_id"] for ref in result.skill_refs}
    assert "recruiting.feedback" in ref_ids


async def test_writer_records_feedback_skill_refs(skills: SkillRegistry) -> None:
    runtime = AgentRuntime(TestModel(call_tools=[]))
    writer = FeedbackWriter(runtime, skills=skills)
    result = await writer.write(
        evaluation=make_evaluation(MIXED),
        candidate_name="Siti Rahma",
        job_title="AI Engineer",
        language="id",
        deps=AgentDeps(tools=ToolRegistry(audit=AuditChain())),
    )
    assert {"skill_id", "version", "hash"} == set(result.skill_refs[0].keys())
