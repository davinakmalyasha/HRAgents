"""The fairness signature compares what a decision could use, not the name."""

from __future__ import annotations

from evals.fairness import compare_pair

from hr_agents.models import CandidateProfile, EducationEntry, Skill, SkillCategory


def profile(
    name: str,
    *,
    skills: tuple[str, ...] = ("Python", "PostgreSQL"),
    institution: str = "Universitas Indonesia",
) -> CandidateProfile:
    return CandidateProfile(
        full_name=name,
        skills=[Skill(name=skill, category=SkillCategory.LANGUAGE) for skill in skills],
        education=[
            EducationEntry(institution=institution, degree="BSc", field_of_study="Computer Science")
        ],
    )


def test_a_name_swap_alone_leaves_the_decision_signature_equal() -> None:
    assert compare_pair([("a", profile("Budi Santoso")), ("b", profile("Siti Rahmawati"))]) == {}


def test_a_different_skill_set_is_divergent() -> None:
    result = compare_pair(
        [("a", profile("Budi")), ("b", profile("Budi", skills=("Python", "Rust")))]
    )

    assert set(result) == {"a", "b"}
    assert result["a"] != result["b"]


def test_a_different_school_is_divergent() -> None:
    result = compare_pair(
        [("a", profile("Budi")), ("b", profile("Budi", institution="Universitas Gadjah Mada"))]
    )

    assert set(result) == {"a", "b"}
