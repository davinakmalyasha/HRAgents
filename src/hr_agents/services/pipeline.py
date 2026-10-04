"""Application pipeline — deterministic orchestration of the evaluation flow.

    received → guard → extract (k runs) → score → aggregate → policy → route

Agents extract and communicate; this module owns sequencing. It performs no
model judgment itself: every routing decision comes from the policy engine and
every step writes to the audit chain.
"""

from __future__ import annotations

import asyncio
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

    scoring_runs: int = 3
    mutual_slots: int | None = None
    reference_date: date | None = None

    @classmethod
    def from_settings(cls) -> PipelineConfig:
        """Build from operator settings, so k is never a silent per-call default."""
        from hr_agents.config import get_settings

        return cls(scoring_runs=get_settings().scoring_runs)


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
    """Everything the pipeline produced for one application, auditable.

    ``profile`` and ``evaluation`` are optional for exactly one reason: when there
    is no active consent, nothing was extracted, and neither model can represent
    "nothing" honestly. `TechnicalEvaluation.runs` requires at least two entries so
    sigma can never be computed from a single extraction, and
    `CandidateProfile.full_name` requires at least one character -- so a halt is not
    a zero score with a blank name, it is the absence of both, and fabricating
    either would put a record on the chain implying a candidate was assessed.

    ``consent_halted`` says which it is. Consumers must check it before reading
    the other two.
    """

    profile: CandidateProfile | None = None
    evaluation: TechnicalEvaluation | None = None
    policy: PolicyEvaluation
    recommendation: Recommendation
    flags: list[EvaluationFlag] = Field(default_factory=list)
    audit_actions: list[str] = Field(default_factory=list)
    consent_halted: bool = False


def _recommendation_for(decision: PolicyDecision) -> Recommendation:
    """Translate a policy decision into what the pipeline recommends.

    Nothing here recommends `REJECT`. That is the point of the change: the
    sub-floor band used to map straight to `Recommendation.REJECT`, so the
    application was written to the store as `REJECTED` before anyone had looked
    at it, and a rejection message was communicable on that record alone. It is
    also the least evidenced decision the engine can reach -- a score below the
    floor, with no human in the loop -- which made asserting it most confident
    exactly where the evidence was weakest.

    A recommendation to reject still arrives; it just carries
    `REJECT_REQUIRES_SIGNOFF`, which is the same request the in-band soft
    rejection has always made. `Recommendation.REJECT` now means only "a person
    already rejected this", written after their recorded override.
    """
    if decision is PolicyDecision.AUTO_SCHEDULE:
        return Recommendation.AUTO_SCHEDULE
    if decision is PolicyDecision.REJECT_AUTO:
        return Recommendation.REJECT_REQUIRES_SIGNOFF
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
        config: PipelineConfig | None = None,
    ) -> None:
        self._deconstructor = deconstructor
        self._storage = storage
        self._audit = audit
        self._guard = guard or InjectionGuard()
        self._config = config

    async def process(
        self,
        *,
        application_id: str,
        resume_text: str,
        job: JobSpecification,
        consent_active: bool,
        config: PipelineConfig | None = None,
    ) -> PipelineResult:
        """Extract, score, and route one application.

        ``consent_active`` is required rather than defaulted. The policy engine has
        always had a consent gate -- ``evaluate_policy`` returns ``HITL_MANUAL``
        with "processing halted pending lawful basis" when it is false -- and this
        call passed ``True`` unconditionally, so the gate could not fire and
        ``ComplianceService.has_active_consent`` had no call site at all.

        Checking it *here*, before the first extraction, is the point rather than
        the routing. By the time the policy decision is computed the résumé has
        already been read, split into k concurrent extraction calls, and sent to
        whichever model the operator configured. Routing it to a human afterwards
        is not a lawful-basis check; it is a filing error. UU PDP 27/2022 makes
        processing personal data without consent the thing being regulated, and
        the data in question is a candidate's name, NIK, address and employment
        history.

        Making it a required keyword means a new caller cannot forget it, which is
        how the previous version shipped.
        """
        config = config or self._config or PipelineConfig.from_settings()
        reference_date = config.reference_date or date.today()
        actions: list[str] = []

        self._audit.append_system(
            action="pipeline.started",
            subject_type="application",
            subject_id=application_id,
            payload={"job_id": str(job.id), "scoring_runs": config.scoring_runs},
        )
        actions.append("pipeline.started")

        if not consent_active:
            self._audit.append_system(
                action="pipeline.halted_no_consent",
                subject_type="application",
                subject_id=application_id,
                payload={
                    "job_id": str(job.id),
                    "reason": "no active consent for recruitment_evaluation; "
                    "the document was not read and no model was called",
                },
            )
            policy = evaluate_policy(
                s_tech=0.0,
                sigma=0.0,
                flags=[EvaluationFlag.CONSENT_MISSING],
                mutual_slots=config.mutual_slots,
                consent_active=False,
            )
            # No profile and no evaluation. `runs` requires at least two
            # extractions so sigma can never come from a single pass, and
            # `full_name` requires at least one character -- so "the document was
            # not read" is not expressible as a zero score with a blank name, and
            # should not be: the record says nothing was evaluated rather than
            # implying an assessment happened.
            return PipelineResult(
                profile=None,
                evaluation=None,
                policy=policy,
                recommendation=_recommendation_for(policy.decision),
                flags=[EvaluationFlag.CONSENT_MISSING],
                audit_actions=[*actions, "pipeline.halted_no_consent"],
                consent_halted=True,
            )

        # 1. Extraction: k independent passes for variance measurement. The runs
        #    are independent by construction, so they run concurrently — k
        #    sequential LLM calls tripled wall-clock time for no added signal.
        flags: list[EvaluationFlag] = []
        max_severity = 0
        deps = AgentDeps(tools=self._storage.tools, audit=self._audit)
        run_count = max(2, config.scoring_runs)

        results = await asyncio.gather(
            *(
                self._deconstructor.deconstruct(
                    resume_text, deps=deps, source_name=f"application:{application_id}"
                )
                for _ in range(run_count)
            )
        )
        profiles: list[CandidateProfile] = []
        for result in results:
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
            consent_active=consent_active,
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
