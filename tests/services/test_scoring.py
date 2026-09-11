from datetime import date

import pytest

from hr_agents.models import (
    CandidateProfile,
    CertificationClaim,
    ExperienceEntry,
    JobSpecification,
    ProjectEntry,
    ScoreDimension,
    Skill,
    SkillCategory,
    VerificationStatus,
)
from hr_agents.services.scoring import normalize_skill, score_candidate, score_runs

REFERENCE = date(2025, 1, 1)


def make_job(**overrides: object) -> JobSpecification:
    defaults: dict[str, object] = {
        "title": "Backend Engineer",
        "must_have_skills": ["Python", "PostgreSQL", "FastAPI"],
        "nice_to_have_skills": ["Docker", "Redis"],
        "stack": ["Python", "FastAPI", "PostgreSQL"],
    }
    defaults.update(overrides)
    return JobSpecification(**defaults)  # type: ignore[arg-type]


def make_profile() -> CandidateProfile:
    return CandidateProfile(
        full_name="Budi Santoso",
        experience=[
            ExperienceEntry(
                company="Nusantara Systems",
                title="Senior Software Engineer",
                start_date=date(2020, 1, 1),
                end_date=date(2023, 1, 1),
                tech_stack=["Python", "FastAPI", "PostgreSQL", "Redis"],
                highlights=[
                    "Designed an event-driven API platform with queue-based ingestion",
                    "Improved p99 latency and throughput across distributed services",
                    "Introduced CI/CD and observability with Docker and Kubernetes",
                ],
            ),
            ExperienceEntry(
                company="Merdeka AI",
                title="Lead Engineer",
                start_date=date(2023, 1, 1),
                end_date=date(2025, 1, 1),
                tech_stack=["Python", "Go", "PydanticAI", "Kafka"],
                highlights=["Built ML platform services with caching and schema registries"],
            ),
        ],
        skills=[
            Skill(name="py", category=SkillCategory.LANGUAGE, claimed_proficiency=5),
            Skill(name="Postgres", category=SkillCategory.DATABASE, claimed_proficiency=5),
            Skill(name="FastAPI", category=SkillCategory.FRAMEWORK, claimed_proficiency=5),
            Skill(name="Kubernetes", category=SkillCategory.DEVOPS, claimed_proficiency=4),
            Skill(name="AWS", category=SkillCategory.CLOUD, claimed_proficiency=4),
            Skill(name="Redis", category=SkillCategory.DATABASE, claimed_proficiency=4),
            Skill(name="Kafka", category=SkillCategory.SYSTEMS, claimed_proficiency=4),
            Skill(name="Pandas", category=SkillCategory.DATA, claimed_proficiency=3),
        ],
        projects=[
            ProjectEntry(name="hr-agents", tech_stack=["Python", "PydanticAI"]),
            ProjectEntry(name="queue-lab", tech_stack=["Go", "Redis"]),
            ProjectEntry(name="ast-explorer", tech_stack=["Python"]),
        ],
        certifications=[
            CertificationClaim(
                name="AWS Solutions Architect",
                issuer="AWS",
                status=VerificationStatus.VERIFIED,
            )
        ],
    )


def test_alias_normalization() -> None:
    assert normalize_skill("Postgres") == "postgresql"
    assert normalize_skill("py") == "python"
    assert normalize_skill("Node.js") == "node"
    assert normalize_skill("K8s") == "kubernetes"
    assert normalize_skill("  FastAPI ") == "fastapi"


def test_strong_candidate_beats_weak_candidate() -> None:
    strong = score_candidate(make_profile(), make_job(), reference_date=REFERENCE)
    weak_profile = CandidateProfile(
        full_name="Weak Candidate",
        experience=[
            ExperienceEntry(
                company="Umbrella Corp",
                title="Junior Web Developer",
                start_date=date(2024, 6, 1),
                end_date=date(2025, 1, 1),
                tech_stack=["PHP", "jQuery"],
            )
        ],
        skills=[Skill(name="PHP", category=SkillCategory.LANGUAGE)],
    )
    weak = score_candidate(weak_profile, make_job(), reference_date=REFERENCE)

    weights = make_job().effective_weights()
    assert strong.s_tech(weights) > weak.s_tech(weights)
    assert strong.vector.technical_depth > weak.vector.technical_depth
    assert strong.vector.stack_alignment > weak.vector.stack_alignment


def test_stack_alignment_combines_all_components() -> None:
    result = score_candidate(make_profile(), make_job(), reference_date=REFERENCE)
    # must-have 3/3 (aliases normalizing Postgres->postgresql, py->python),
    # nice-to-have 1/2 (Redis yes, Docker no), stack 3/3
    # -> (0.60*1.0 + 0.25*0.5 + 0.15*1.0) = 0.875
    assert result.vector.stack_alignment == pytest.approx(0.875)
    rationale = result.breakdown[1].rationale
    assert "must-have: 3/3 matched" in rationale
    assert "missing: docker" in rationale


def test_stack_alignment_reports_missing_skills() -> None:
    job = make_job(must_have_skills=["Python", "Rust"], nice_to_have_skills=[], stack=[])
    result = score_candidate(make_profile(), job, reference_date=REFERENCE)
    assert result.vector.stack_alignment == pytest.approx(0.5)
    assert "missing: rust" in result.breakdown[1].rationale


def test_no_requirements_is_neutral() -> None:
    job = make_job(must_have_skills=[], nice_to_have_skills=[], stack=[])
    result = score_candidate(make_profile(), job, reference_date=REFERENCE)
    assert result.vector.stack_alignment == pytest.approx(0.5)
    assert "neutral" in result.breakdown[1].rationale


def test_no_certifications_scores_zero() -> None:
    profile = make_profile().model_copy(update={"certifications": []})
    result = score_candidate(profile, make_job(), reference_date=REFERENCE)
    assert result.vector.verifiable_certifications == 0.0


def test_verified_certification_math() -> None:
    profile = make_profile()
    result = score_candidate(profile, make_job(), reference_date=REFERENCE)
    # 1/1 verified -> 0.7 * 1.0 + 0.3 * (1/3) = 0.8
    assert result.vector.verifiable_certifications == pytest.approx(0.8, abs=1e-6)


def test_tenure_math_from_dates() -> None:
    result = score_candidate(make_profile(), make_job(), reference_date=REFERENCE)
    assert "60 months experience" in result.breakdown[0].rationale


def test_determinism_same_input_same_output() -> None:
    first = score_candidate(make_profile(), make_job(), reference_date=REFERENCE)
    second = score_candidate(make_profile(), make_job(), reference_date=REFERENCE)
    assert first == second


def test_breakdown_carries_weights_from_job() -> None:
    job = make_job(
        dimension_weights={
            ScoreDimension.TECHNICAL_DEPTH: 1.0,
            ScoreDimension.STACK_ALIGNMENT: 0.0,
            ScoreDimension.SYSTEMS_LITERACY: 0.0,
            ScoreDimension.VERIFIABLE_CERTIFICATIONS: 0.0,
        }
    )
    result = score_candidate(make_profile(), job, reference_date=REFERENCE)
    assert result.breakdown[0].weight == pytest.approx(1.0)
    assert result.s_tech(job.effective_weights()) == pytest.approx(result.vector.technical_depth)


def test_score_runs_returns_one_result_per_profile() -> None:
    profiles = [make_profile(), make_profile()]
    results = score_runs(profiles, make_job(), reference_date=REFERENCE)
    assert len(results) == 2
    assert results[0] == results[1]


def test_all_scores_bounded() -> None:
    result = score_candidate(make_profile(), make_job(), reference_date=REFERENCE)
    for value in result.vector.as_mapping().values():
        assert 0.0 <= value <= 1.0
