from datetime import date

import pytest

from hr_agents.models import (
    CandidateProfile,
    ExperienceEntry,
    JobSpecification,
    Skill,
    SkillCategory,
)
from hr_agents.services.fairness import (
    DEFAULT_SWAPS,
    run_audit_suite,
    run_name_swap_audit,
    summarize,
)
from hr_agents.services.scoring import ScoringResult

REFERENCE = date(2025, 1, 1)


def make_profile(name: str = "Budi Santoso", city: str = "Jakarta") -> CandidateProfile:
    return CandidateProfile(
        full_name=name,
        experience=[
            ExperienceEntry(
                company="Nusantara Systems",
                title="Senior Software Engineer",
                start_date=date(2020, 1, 1),
                end_date=date(2024, 6, 30),
                tech_stack=["Python", "FastAPI", "PostgreSQL"],
                highlights=["Built queue-based ingestion", "Improved p99 latency"],
            )
        ],
        skills=[
            Skill(name="Python", category=SkillCategory.LANGUAGE),
            Skill(name="PostgreSQL", category=SkillCategory.DATABASE),
        ],
        location={"city": city, "timezone": "Asia/Jakarta"},  # type: ignore[arg-type]
    )


def make_job() -> JobSpecification:
    return JobSpecification(
        title="Backend Engineer",
        must_have_skills=["Python", "PostgreSQL"],
        stack=["FastAPI"],
    )


def test_name_and_city_swaps_do_not_change_scores() -> None:
    report = run_name_swap_audit(make_profile(), make_job(), reference_date=REFERENCE)

    assert report.passed, report.violations
    # 4 names + 4 cities, minus the identical baseline name and city = 6
    assert report.profiles_tested == 6


def test_audit_suite_summary() -> None:
    profiles = [
        make_profile("Budi Santoso", "Jakarta"),
        make_profile("Siti Rahma", "Bandung"),
    ]
    reports = run_audit_suite(profiles, make_job(), reference_date=REFERENCE)
    summary = summarize(reports)

    assert summary.passed
    assert summary.profiles_tested == 2
    assert summary.violations == 0
    assert summary.total_counterfactuals == 12


def test_default_swaps_include_the_study_names() -> None:
    names = DEFAULT_SWAPS["full_name"]
    assert "Budi Santoso" in names
    assert "Siti Rahma" in names
    assert "Michael Chen" in names


def test_unsupported_swap_path_raises() -> None:
    with pytest.raises(ValueError, match="unsupported swap path"):
        run_name_swap_audit(
            make_profile(),
            make_job(),
            reference_date=REFERENCE,
            swaps={"salary.monthly": ["10m"]},
        )


def test_violation_detected_when_score_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove the harness catches real invariance breaks (via injected bug)."""
    from hr_agents.services import fairness

    original = fairness.score_candidate

    def rigged(
        profile: CandidateProfile,
        job: JobSpecification,
        *,
        reference_date: date,
    ) -> ScoringResult:
        result = original(profile, job, reference_date=reference_date)
        if profile.full_name == "Michael Chen":
            vector = result.vector.model_copy(update={"technical_depth": 0.01})
            return result.model_copy(update={"vector": vector})
        return result

    monkeypatch.setattr(fairness, "score_candidate", rigged)
    report = run_name_swap_audit(make_profile(), make_job(), reference_date=REFERENCE)

    assert not report.passed
    assert any(violation.variant_value == "Michael Chen" for violation in report.violations)
