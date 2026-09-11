"""Application pipeline — deterministic orchestration of the evaluation flow.

    received → guard → extract (k runs) → score → aggregate → policy → route

Agents extract and communicate; this module owns sequencing. It performs no
model judgment itself: every routing decision comes from the policy engine and
every step writes to the audit chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.injection_guard import InjectionGuard
from hr_agents.agents.resume_deconstructor import ResumeDeconstructor
from hr_agents.models import (
    CandidateProfile,
    EvaluationFlag,
    JobSpecification,
    PolicyDecision,
    PolicyEvaluation,
    Recommendation,
    ScoringRun,
    StrictModel,
    TechnicalEvaluation,
    aggregate_runs,
    utc_now,
)
from hr_agents.services.audit import AuditChain
from hr_agents.services.policy import evaluate_policy
from hr_agents.services.scoring import ScoringResult, score_candidate
from hr_agents.tools.registry import ToolRegistry


@dataclass
class PipelineConfig:
    """Configuration for one pipeline execution."""

    scoring_runs: int = 1
    mutual_slots: int | None = None
    reference_date: date | None = None


class StoragePort(Protocol):
    """Persistence contract for pipeline output (memory now, Postgres later)."""

    @property
    def tools(self) -> ToolRegistry: ...

    async def persist(
        self,
        *,
        application_id: str,
        profile: CandidateProfile,
        evaluation: TechnicalEvaluation,
    ) -> None: ...


class InMemoryStorage:
    """Simple storage adapter for tests and single-process runs."""

    def __init__(self, tools: ToolRegistry) -> None:
        self._tools = tools
        self.saved: dict[str, tuple[CandidateProfile, TechnicalEvaluation]] = {}

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    async def persist(
        self,
        *,
        application_id: str,
        profile: CandidateProfile,
        evaluation: TechnicalEvaluation,
    ) -> None:
        self.saved[application_id] = (profile, evaluation)


class PipelineResult(StrictModel):
    """Everything the pipeline produced for one application, auditable."""

    profile: CandidateProfile
    evaluation: TechnicalEvaluation
    policy: PolicyEvaluation
    recommendation: Recommendation
    flags: list[EvaluationFlag] = Field(default_factory=list)
    audit_actions: list[str] = Field(default_factory=list)


def _recommendation_for(decision: PolicyDecision) -> Recommendation:
    if decision is PolicyDecision.AUTO_SCHEDULE:
        return Recommendation.AUTO_SCHEDULE
    if decision is PolicyDecision.REJECT_AUTO:
        return Recommendation.REJECT
    if decision is PolicyDecision.HITL_SOFT_REJECTION:
        return Recommendation.REJECT_REQUIRES_SIGNOFF
    return Recommendation.HUMAN_REVIEW


def _to_scoring_run(index: int, result: ScoringResult, application_id: str) -> ScoringRun:
    return ScoringRun(
        run_index=index,
        extraction_id=uuid5(NAMESPACE_URL, f"{application_id}:{index}"),
        vector=result.vector,
    )


class ApplicationPipeline:
    """Orchestrates one application end-to-end, deterministically."""

    def __init__(
        self,
        *,
        deconstructor: ResumeDeconstructor,
        storage: StoragePort,
        audit: AuditChain,
        guard: InjectionGuard | None = None,
    ) -> None:
        self._deconstructor = deconstructor
        self._storage = storage
        self._audit = audit
        self._guard = guard or InjectionGuard()

    async def process(
        self,
        *,
        application_id: str,
        resume_text: str,
        job: JobSpecification,
        config: PipelineConfig | None = None,
    ) -> PipelineResult:
        config = config or PipelineConfig()
        reference_date = config.reference_date or date.today()
        actions: list[str] = []

        self._audit.append_system(
            action="pipeline.started",
            subject_type="application",
            subject_id=application_id,
            payload={"job_id": str(job.id), "scoring_runs": config.scoring_runs},
        )
        actions.append("pipeline.started")

        # 1. Extraction: k independent passes for variance measurement
        profiles: list[CandidateProfile] = []
        flags: list[EvaluationFlag] = []
        max_severity = 0
        deps = AgentDeps(tools=self._storage.tools, audit=self._audit)

        for _run_index in range(max(1, config.scoring_runs)):
            result = await self._deconstructor.deconstruct(
                resume_text, deps=deps, source_name=f"application:{application_id}"
            )
            profiles.append(result.profile)
            max_severity = max(max_severity, result.guard.risk_severity)
            if result.guard.blocking:
                flags.append(EvaluationFlag.INJECTION_SUSPECTED)

        if EvaluationFlag.INJECTION_SUSPECTED in flags:
            self._audit.append_system(
                action="pipeline.injection_flagged",
                subject_type="application",
                subject_id=application_id,
                payload={"severity": max_severity},
            )
            actions.append("pipeline.injection_flagged")

        primary = profiles[0]

        # 2. Deterministic scoring per extraction, then aggregation
        scoring = [
            score_candidate(profile, job, reference_date=reference_date) for profile in profiles
        ]
        runs = [
            _to_scoring_run(index, result, application_id) for index, result in enumerate(scoring)
        ]
        mean_vector, dimension_stddev, s_tech, sigma = aggregate_runs(
            runs, weights=job.effective_weights()
        )

        if sigma > 0.10:
            flags.append(EvaluationFlag.INCONSISTENT_RUNS)

        # 3. Policy decision (deterministic routing)
        evaluation = TechnicalEvaluation(
            candidate_id=primary.id,
            job_id=job.id,
            runs=runs,
            mean_vector=mean_vector,
            dimension_stddev=dimension_stddev,
            s_tech=s_tech,
            sigma=sigma,
            weights=job.effective_weights(),
            breakdown=scoring[0].breakdown,
            flags=sorted({flag for flag in flags}, key=lambda item: item.value),
            recommendation=Recommendation.HUMAN_REVIEW,  # replaced below
            created_at=utc_now(),
        )

        policy = evaluate_policy(
            s_tech=s_tech,
            sigma=sigma,
            flags=evaluation.flags,
            mutual_slots=config.mutual_slots,
            consent_active=True,
        )
        recommendation = _recommendation_for(policy.decision)
        evaluation = evaluation.model_copy(update={"recommendation": recommendation})

        # 4. Audit + persist
        self._audit.append_system(
            action=f"pipeline.decision.{policy.decision.value}",
            subject_type="application",
            subject_id=application_id,
            payload={
                "s_tech": round(s_tech, 6),
                "sigma": round(sigma, 6),
                "recommendation": recommendation.value,
                "flags": [flag.value for flag in evaluation.flags],
            },
        )
        actions.append(f"pipeline.decision.{policy.decision.value}")

        await self._storage.persist(
            application_id=application_id, profile=primary, evaluation=evaluation
        )
        actions.append("pipeline.persisted")

        return PipelineResult(
            profile=primary,
            evaluation=evaluation,
            policy=policy,
            recommendation=recommendation,
            flags=evaluation.flags,
            audit_actions=actions,
        )
