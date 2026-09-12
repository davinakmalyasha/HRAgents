"""Tests for the read-only evaluation breakdown tool."""

from uuid import uuid4

import pytest

from hr_agents.models import (
    DimensionScore,
    EvaluationFlag,
    PolicyDecision,
    PolicyEvaluation,
    Recommendation,
    ScoreDimension,
    ScoreVector,
    ScoringRun,
    TechnicalEvaluation,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.recruiting import EvaluationRecord
from hr_agents.tools import (
    ToolPermissionError,
    ToolRegistry,
    make_get_evaluation_breakdown_tool,
    serialize_breakdown,
)


def _record() -> EvaluationRecord:
    vector = ScoreVector(
        technical_depth=0.9,
        stack_alignment=0.8,
        systems_literacy=0.7,
        verifiable_certifications=0.6,
    )
    evaluation = TechnicalEvaluation(
        candidate_id=uuid4(),
        job_id=uuid4(),
        runs=[ScoringRun(run_index=0, extraction_id=uuid4(), vector=vector)],
        mean_vector=vector,
        s_tech=0.9,
        sigma=0.02,
        breakdown=[
            DimensionScore(
                dimension=dimension,
                score=0.9,
                weight=0.25,
                rationale="evidence reviewed",
            )
            for dimension in ScoreDimension
        ],
        flags=[EvaluationFlag.INJECTION_SUSPECTED],
        recommendation=Recommendation.HUMAN_REVIEW,
    )
    return EvaluationRecord(
        application_id=uuid4(),
        candidate_id=evaluation.candidate_id,
        candidate_name="Budi Santoso",
        job_id=evaluation.job_id,
        job_title="Backend Engineer",
        evaluation=evaluation,
        policy=PolicyEvaluation(decision=PolicyDecision.HITL_ANOMALY, reasons=["flag present"]),
    )


def _registry(record: EvaluationRecord | None) -> ToolRegistry:
    tools = ToolRegistry(audit=AuditChain())
    tools.register(
        make_get_evaluation_breakdown_tool(
            lambda candidate_id: serialize_breakdown(record) if record is not None else None
        )
    )
    return tools


async def test_breakdown_tool_executes_for_allowed_agents() -> None:
    record = _record()
    result = await _registry(record).execute(
        agent_name="feedback_writer",
        tool_name="get_evaluation_breakdown",
        arguments={"candidate_id": str(record.candidate_id)},
    )
    assert result["s_tech"] == 0.9
    assert result["policy_decision"] == "hitl_anomaly"
    assert result["dimensions"][0]["rationale"] == "evidence reviewed"


async def test_breakdown_tool_denied_for_other_agents() -> None:
    with pytest.raises(ToolPermissionError):
        await _registry(_record()).execute(
            agent_name="resume_deconstructor",
            tool_name="get_evaluation_breakdown",
            arguments={"candidate_id": "cand-1"},
        )


async def test_breakdown_tool_reports_missing_evaluation() -> None:
    result = await _registry(None).execute(
        agent_name="screening_coordinator",
        tool_name="get_evaluation_breakdown",
        arguments={"candidate_id": "cand-1"},
    )
    assert "error" in result


def test_serialize_breakdown_omits_protected_fields() -> None:
    payload = serialize_breakdown(_record())
    assert not {"candidate_name", "email", "phone", "birth_date"} & set(payload)
    assert payload["flags"] == ["injection_suspected"]
    assert payload["candidate_id"]
