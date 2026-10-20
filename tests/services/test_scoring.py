from datetime import date

import pytest

from hr_agents.models import (
    CandidateProfile,
    CertificationClaim,
    DimensionScore,
    EvidenceRef,
    ExperienceEntry,
    JobSpecification,
    ProjectEntry,
    ScoreDimension,
    Skill,
    SkillCategory,
    SourceType,
    VerificationStatus,
)
from hr_agents.services.dimensions import ENGINEERING
from hr_agents.services.scoring import (
    dimensions_evidenced,
    normalize_skill,
    score_candidate,
    score_runs,
)

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


def test_an_explicit_template_overrides_the_family_default() -> None:
    """The pipeline resolves the active rubric; scoring must use what it is given."""
    template = ENGINEERING.model_copy(
        update={
            "professional_categories": frozenset({SkillCategory.OTHER}),
            "signal_keywords": ("quantum accounting",),
            "signal_saturation": 1,
            "title_tiers": ((frozenset({"chief executive"}), 1.0),),
        }
    )
    profile = make_profile()
    job = make_job()
    default = score_candidate(profile, job, reference_date=REFERENCE)
    narrowed = score_candidate(profile, job, reference_date=REFERENCE, template=template)

    assert narrowed.vector.systems_literacy < default.vector.systems_literacy
    assert narrowed.vector.technical_depth == default.vector.technical_depth


def _sourced(profile: CandidateProfile) -> CandidateProfile:
    """The same profile with one provenance reference on every record."""
    source = EvidenceRef(
        source_type=SourceType.RESUME, locator="cv.pdf", excerpt="extracted from the CV"
    )
    return profile.model_copy(
        update={
            "skills": [skill.model_copy(update={"evidence": [source]}) for skill in profile.skills],
            "experience": [
                entry.model_copy(update={"evidence": [source]}) for entry in profile.experience
            ],
            "projects": [
                project.model_copy(update={"evidence": [source]}) for project in profile.projects
            ],
            "certifications": [
                cert.model_copy(update={"evidence": [source]}) for cert in profile.certifications
            ],
        }
    )


def test_evidence_flows_to_every_dimension_without_changing_scores() -> None:
    plain = score_candidate(make_profile(), make_job(), reference_date=REFERENCE)
    sourced = score_candidate(_sourced(make_profile()), make_job(), reference_date=REFERENCE)

    assert sourced.vector == plain.vector
    assert dimensions_evidenced(sourced.breakdown)
    assert not dimensions_evidenced(plain.breakdown)
    for item in sourced.breakdown:
        assert item.evidence, item.dimension


def test_evidence_is_deduplicated_and_stable() -> None:
    profile = _sourced(make_profile())
    first = score_candidate(profile, make_job(), reference_date=REFERENCE)
    second = score_candidate(profile, make_job(), reference_date=REFERENCE)

    for left, right in zip(first.breakdown, second.breakdown, strict=True):
        left_keys = [(ref.source_type, ref.locator, ref.excerpt) for ref in left.evidence]
        right_keys = [(ref.source_type, ref.locator, ref.excerpt) for ref in right.evidence]
        assert left_keys == right_keys
        assert len(left_keys) == len(set(left_keys))


def test_dimensions_evidenced_enforces_the_confidence_floor() -> None:
    weak = EvidenceRef(source_type=SourceType.RESUME, locator="cv.pdf", confidence=0.2)
    strong = weak.model_copy(update={"confidence": 0.9})
    breakdown = [
        DimensionScore(
            dimension=dimension,
            score=0.5,
            weight=0.25,
            rationale="",
            evidence=[weak],
        )
        for dimension in ScoreDimension
    ]

    assert not dimensions_evidenced(breakdown)
    mixed = [
        item.model_copy(update={"evidence": [strong]}) if index == 0 else item
        for index, item in enumerate(breakdown)
    ]
    assert not dimensions_evidenced(mixed)
    assert dimensions_evidenced(
        [item.model_copy(update={"evidence": [strong]}) for item in breakdown]
    )
