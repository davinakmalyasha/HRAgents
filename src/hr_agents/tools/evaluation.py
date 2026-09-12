"""Evaluation tools: read-only access to the deterministic score breakdown."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from hr_agents.tools.registry import ToolDefinition

if TYPE_CHECKING:
    from hr_agents.services.recruiting import EvaluationRecord

_EVALUATION_AGENTS = frozenset({"feedback_writer", "screening_coordinator"})

EvaluationLookup = Callable[[str], dict[str, Any] | None]


def serialize_breakdown(record: EvaluationRecord) -> dict[str, Any]:
    """Serialize one evaluation record for agent context.

    Structured facts only: dimension scores, weights, rationale, flags, and the
    deterministic recommendation. No protected attributes, no raw document text.
    """
    evaluation = record.evaluation
    return {
        "candidate_id": str(record.candidate_id),
        "job_title": record.job_title,
        "s_tech": round(evaluation.s_tech, 4),
        "sigma": round(evaluation.sigma, 4),
        "recommendation": evaluation.recommendation.value,
        "policy_decision": record.policy.decision.value,
        "flags": [flag.value for flag in evaluation.flags],
        "dimensions": [
            {
                "dimension": item.dimension.value,
                "score": round(item.score, 4),
                "weight": item.weight,
                "rationale": item.rationale,
            }
            for item in evaluation.breakdown
        ],
    }


def make_get_evaluation_breakdown_tool(lookup: EvaluationLookup) -> ToolDefinition:
    """Read-only lookup of one candidate's evaluation breakdown."""

    def get_evaluation_breakdown(candidate_id: str) -> dict[str, object]:
        """Fetch the candidate's deterministic score breakdown and flags."""
        evaluation = lookup(candidate_id)
        if evaluation is None:
            return {"error": f"no evaluation for candidate {candidate_id}"}
        return evaluation

    return ToolDefinition(
        name="get_evaluation_breakdown",
        description=(
            "Fetch the candidate's deterministic score breakdown (dimensions, "
            "weights, rationale), flags, and policy decision. Read-only: use it "
            "to ground feedback in evidence; it is never a decision."
        ),
        allowed_agents=_EVALUATION_AGENTS,
        handler=get_evaluation_breakdown,
        tags=frozenset({"evaluation", "read"}),
    )
