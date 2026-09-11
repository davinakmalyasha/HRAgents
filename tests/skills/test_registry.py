from pathlib import Path

import pytest

from hr_agents.skills import SkillLibrary, SkillRegistry, load_library

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


@pytest.fixture
def registry() -> SkillRegistry:
    return SkillRegistry(load_library(SKILLS_ROOT))


def test_get_known_skill(registry: SkillRegistry) -> None:
    skill = registry.get("recruiting.screening")
    assert skill.manifest.name == "Candidate Screening Runbook"


def test_get_unknown_skill_raises(registry: SkillRegistry) -> None:
    with pytest.raises(KeyError, match="unknown skill id"):
        registry.get("recruiting.nonexistent")


def test_contains(registry: SkillRegistry) -> None:
    assert "recruiting.screening" in registry
    assert "nope" not in registry


def test_for_agent_returns_only_allowed(registry: SkillRegistry) -> None:
    screening = registry.for_agent("screening_coordinator")
    ids = {skill.id for skill in screening}

    assert "recruiting.screening" in ids
    assert "platform.compliance" in ids
    assert "recruiting.feedback" not in ids


def test_for_agent_unknown_returns_empty(registry: SkillRegistry) -> None:
    assert registry.for_agent("nonexistent_agent") == []


def test_for_department(registry: SkillRegistry) -> None:
    recruiting = registry.for_department("recruiting")
    assert {skill.id for skill in recruiting} == {
        "recruiting.screening",
        "recruiting.evaluation",
        "recruiting.feedback",
    }


def test_knowledge_for_namespace_prefix(registry: SkillRegistry) -> None:
    docs = registry.knowledge_for("recruiting")
    namespaces = {doc.namespace for doc in docs}

    assert namespaces <= {"recruiting.evaluation", "recruiting.feedback"}
    assert "platform.compliance" not in namespaces


def test_knowledge_for_exact_namespace(registry: SkillRegistry) -> None:
    docs = registry.knowledge_for("recruiting.evaluation")
    ids = {doc.id for doc in docs}
    assert {"backend-rubric", "ai-engineer-rubric"} <= ids


def test_knowledge_namespaces_sorted(registry: SkillRegistry) -> None:
    namespaces = registry.knowledge_namespaces()
    assert namespaces == sorted(namespaces)


def test_fingerprint_deterministic(registry: SkillRegistry) -> None:
    fresh = SkillRegistry(load_library(SKILLS_ROOT))
    assert registry.fingerprint() == fresh.fingerprint()
    assert len(registry.fingerprint()) == 64


def test_audit_refs_cover_all_skills(registry: SkillRegistry) -> None:
    refs = registry.audit_refs()
    assert len(refs) == len(registry)
    for ref in refs:
        assert set(ref) == {"skill_id", "version", "hash"}
        assert len(ref["hash"]) == 64


def test_duplicate_skill_id_in_constructor() -> None:
    skills = load_library(SKILLS_ROOT)
    duplicated = [skills[0], skills[0]]
    with pytest.raises(ValueError, match="duplicate skill id"):
        SkillRegistry(duplicated)


def test_library_registry_roundtrip() -> None:
    library = SkillLibrary(skills=load_library(SKILLS_ROOT))
    registry = library.registry()
    assert len(registry) == len(library.skills)
    assert len(library.knowledge) == len(registry.knowledge())
