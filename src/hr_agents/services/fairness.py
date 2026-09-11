"""Fairness harness — counterfactual invariance testing.

The literature (Bertrand & Mullainathan 2004; Quillian et al. 2017) shows names
and demographic markers drive human screening outcomes. This harness proves the
deterministic pipeline is invariant to them: score identical profiles that
differ only in a name or marker and assert bit-for-bit equal outputs.

Run in CI on every change, and as a periodic audit job over real scoring paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic import Field

from hr_agents.models import CandidateProfile, JobSpecification, StrictModel
from hr_agents.services.scoring import score_candidate


class InvarianceViolation(StrictModel):
    """A place where a non-job-relevant attribute changed a score."""

    attribute: str
    baseline_value: str
    variant_value: str
    detail: str


@dataclass
class FairnessReport:
    """Outcome of one counterfactual audit."""

    job_title: str
    profiles_tested: int = 0
    violations: list[InvarianceViolation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations


# Markers the harness swaps. These must never affect any score dimension.
DEFAULT_SWAPS: dict[str, list[str]] = {
    "full_name": ["Budi Santoso", "Siti Rahma", "Michael Chen", "Aisha Rahman"],
    "location.city": ["Jakarta", "Surabaya", "Bandung", "Medan"],
}


def _apply_swap(profile: CandidateProfile, path: str, value: str) -> CandidateProfile:
    if path == "full_name":
        return profile.model_copy(update={"full_name": value})
    if path == "location.city":
        location = profile.location.model_copy(update={"city": value})
        return profile.model_copy(update={"location": location})
    raise ValueError(f"unsupported swap path: {path!r}")


def run_name_swap_audit(
    profile: CandidateProfile,
    job: JobSpecification,
    *,
    reference_date: date,
    swaps: dict[str, list[str]] | None = None,
) -> FairnessReport:
    """Score counterfactual variants; any score change is a violation.

    The audit asserts exact equality of the full score vector and the
    weighted total — not approximate equality — because the pipeline is
    deterministic by design.
    """
    swap_spec = swaps or DEFAULT_SWAPS
    report = FairnessReport(job_title=job.title)

    baseline = score_candidate(profile, job, reference_date=reference_date)
    weights = job.effective_weights()
    baseline_total = baseline.s_tech(weights)

    for attribute, values in swap_spec.items():
        for value in values:
            variant = _apply_swap(profile, attribute, value)
            if variant == profile:
                continue
            report.profiles_tested += 1

            result = score_candidate(variant, job, reference_date=reference_date)
            total = result.s_tech(weights)

            if result.vector != baseline.vector:
                changed = [
                    dimension.value
                    for dimension, score in result.vector.as_mapping().items()
                    if baseline.vector.as_mapping()[dimension] != score
                ]
                report.violations.append(
                    InvarianceViolation(
                        attribute=attribute,
                        baseline_value=getattr(profile, attribute.split(".")[0], "")
                        if "." not in attribute
                        else (profile.location.city or ""),
                        variant_value=value,
                        detail=f"score vector changed in: {', '.join(changed)}",
                    )
                )
            elif total != baseline_total:
                report.violations.append(
                    InvarianceViolation(
                        attribute=attribute,
                        baseline_value="(baseline)",
                        variant_value=value,
                        detail=f"weighted total changed: {baseline_total} -> {total}",
                    )
                )

    return report


def run_audit_suite(
    profiles: list[CandidateProfile],
    job: JobSpecification,
    *,
    reference_date: date,
) -> list[FairnessReport]:
    """Run the counterfactual audit for many profiles."""
    return [
        run_name_swap_audit(profile, job, reference_date=reference_date) for profile in profiles
    ]


class AuditSummary(StrictModel):
    """Aggregate result for dashboards and the paper's fairness section."""

    profiles_tested: int = Field(ge=0)
    total_counterfactuals: int = Field(ge=0)
    violations: int = Field(ge=0)

    @property
    def passed(self) -> bool:
        return self.violations == 0


def summarize(reports: list[FairnessReport]) -> AuditSummary:
    return AuditSummary(
        profiles_tested=len(reports),
        total_counterfactuals=sum(report.profiles_tested for report in reports),
        violations=sum(len(report.violations) for report in reports),
    )
