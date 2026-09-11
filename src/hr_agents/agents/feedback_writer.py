"""FeedbackWriter Agent.

Writes candidate-facing feedback strictly from the deterministic score
breakdown. A deterministic validator then checks the report's grounding before
anything can be sent: strengths must map to strong dimensions, growth areas to
weaker ones, and no protected-attribute language may appear.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field
from pydantic_ai import Agent

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.runtime import AgentRuntime
from hr_agents.agents.skill_context import skill_instructions
from hr_agents.models import (
    FeedbackReport,
    ScoreDimension,
    StrictModel,
    TechnicalEvaluation,
)
from hr_agents.skills.registry import SkillRegistry

AGENT_NAME = "feedback_writer"

STRENGTH_MIN_SCORE = 0.6
GROWTH_MAX_SCORE = 0.75

_PROTECTED_TERMS = (
    "age",
    "gender",
    "religion",
    "married",
    "marital",
    "pregnant",
    "ethnic",
    "race",
    "photo",
    "birth",
    "agama",
    "nikah",
    "usia",
    "hamil",
    "suku",
)

_BASE_INSTRUCTIONS = """\
You are the Feedback Writer agent. You write candidate-facing feedback reports
grounded ONLY in the deterministic score breakdown provided in the prompt.

Hard rules:
- Every strength must reference a dimension that scored well; every growth area
  a dimension that scored lower. Use the provided numbers, not your own view.
- Never mention protected attributes (age, gender, religion, marital status,
  photos, ethnicity, birth dates) — in any language.
- Never mention internal reviewers, other candidates, or raw model output.
- Growth areas describe missing evidence, not ability: "Docker was not
  demonstrated in the reviewed material", never "you don't know Docker".
- Write in the requested language (en or id), plain and respectful, no numeric
  scores in the prose.
- Include the process note and the correction notice fields verbatim in spirit:
  evidence-based review, human-signed, and how to report extraction errors.
"""


class GroundingCode(StrEnum):
    STRENGTH_BELOW_THRESHOLD = "strength_below_threshold"
    GROWTH_ABOVE_THRESHOLD = "growth_above_threshold"
    DUPLICATE_DIMENSION = "duplicate_dimension"
    PROTECTED_ATTRIBUTE = "protected_attribute"
    NO_STRENGTHS = "no_strengths"


class GroundingViolation(StrictModel):
    code: GroundingCode
    detail: str
    dimension: ScoreDimension | None = None


class FeedbackResult(StrictModel):
    report: FeedbackReport
    violations: list[GroundingViolation] = Field(default_factory=list)
    skill_refs: list[dict[str, str]] = Field(default_factory=list)

    @property
    def passes_grounding(self) -> bool:
        return not self.violations


def validate_grounding(
    report: FeedbackReport,
    evaluation: TechnicalEvaluation,
    *,
    strength_min_score: float = STRENGTH_MIN_SCORE,
    growth_max_score: float = GROWTH_MAX_SCORE,
) -> list[GroundingViolation]:
    """Deterministic check that the report matches the score breakdown."""
    scores = evaluation.mean_vector.as_mapping()
    violations: list[GroundingViolation] = []

    if not report.strengths:
        violations.append(
            GroundingViolation(
                code=GroundingCode.NO_STRENGTHS,
                detail="report contains no strengths",
            )
        )

    seen: set[ScoreDimension] = set()
    for strength in report.strengths:
        if strength.dimension in seen:
            violations.append(
                GroundingViolation(
                    code=GroundingCode.DUPLICATE_DIMENSION,
                    detail=f"dimension {strength.dimension.value} used more than once",
                    dimension=strength.dimension,
                )
            )
        seen.add(strength.dimension)
        if scores[strength.dimension] < strength_min_score:
            violations.append(
                GroundingViolation(
                    code=GroundingCode.STRENGTH_BELOW_THRESHOLD,
                    detail=(
                        f"strength cites {strength.dimension.value} "
                        f"(score {scores[strength.dimension]:.2f} < {strength_min_score:.2f})"
                    ),
                    dimension=strength.dimension,
                )
            )

    for growth in report.growth_areas:
        if scores[growth.dimension] > growth_max_score:
            violations.append(
                GroundingViolation(
                    code=GroundingCode.GROWTH_ABOVE_THRESHOLD,
                    detail=(
                        f"growth area cites {growth.dimension.value} "
                        f"(score {scores[growth.dimension]:.2f} > {growth_max_score:.2f})"
                    ),
                    dimension=growth.dimension,
                )
            )

    haystack = " ".join(
        [
            report.summary,
            report.process_note,
            report.correction_notice,
            *(item.text for item in report.strengths),
            *(item.text for item in report.growth_areas),
        ]
    ).lower()
    for term in _PROTECTED_TERMS:
        if term in haystack:
            violations.append(
                GroundingViolation(
                    code=GroundingCode.PROTECTED_ATTRIBUTE,
                    detail=f"protected-attribute term {term!r} appears in the report",
                )
            )

    return violations


class FeedbackWriter:
    """Wraps the PydanticAI agent plus deterministic grounding validation."""

    agent_name = AGENT_NAME

    def __init__(self, runtime: AgentRuntime, *, skills: SkillRegistry) -> None:
        instructions, self._skill_refs = skill_instructions(skills, AGENT_NAME)
        self._runtime = runtime
        self._agent: Agent[AgentDeps, FeedbackReport] = Agent(
            model=runtime.model,
            deps_type=AgentDeps,
            output_type=runtime.structured_output(FeedbackReport),
            name=AGENT_NAME,
            instructions=f"{_BASE_INSTRUCTIONS}\n\n{instructions}".strip(),
            retries=runtime.limits.output_retries,
        )

    async def write(
        self,
        *,
        evaluation: TechnicalEvaluation,
        candidate_name: str,
        job_title: str,
        language: str = "en",
        deps: AgentDeps,
    ) -> FeedbackResult:
        prompt = (
            f"Candidate name: {candidate_name}\n"
            f"Job title: {job_title}\n"
            f"Language: {language}\n"
            f"Score breakdown (deterministic, use these numbers as the only basis):\n"
            f"{evaluation.model_dump_json(indent=2)}"
        )
        result = await self._agent.run(prompt, deps=deps, usage_limits=self._runtime.usage_limits())
        report = result.output
        violations = validate_grounding(report, evaluation)
        return FeedbackResult(
            report=report,
            violations=violations,
            skill_refs=list(self._skill_refs),
        )
