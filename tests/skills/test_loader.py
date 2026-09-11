from pathlib import Path

import pytest

from hr_agents.skills.loader import (
    SkillFormatError,
    discover_skill_paths,
    library_fingerprint,
    load_library,
    load_skill,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


def write_skill(tmp_path: Path, relative: str, content: str) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


VALID_SKILL = """---
id: demo.sample
name: Sample Skill
description: A sample skill for tests.
version: 1.2.3
department: demo
agents: [test_agent]
tags: [test]
---

# Sample runbook

Do the thing carefully.
"""


def test_loads_valid_skill(tmp_path: Path) -> None:
    write_skill(tmp_path, "demo/sample/SKILL.md", VALID_SKILL)
    skills = load_library(tmp_path)

    assert len(skills) == 1
    skill = skills[0]
    assert skill.id == "demo.sample"
    assert skill.manifest.version == "1.2.3"
    assert skill.manifest.agents == ["test_agent"]
    assert "Do the thing carefully." in skill.instructions
    assert len(skill.content_hash) == 64


def test_missing_frontmatter_rejected(tmp_path: Path) -> None:
    write_skill(tmp_path, "demo/sample/SKILL.md", "# No frontmatter\n")
    with pytest.raises(SkillFormatError, match="frontmatter"):
        load_library(tmp_path)


def test_unterminated_frontmatter_rejected(tmp_path: Path) -> None:
    write_skill(tmp_path, "demo/sample/SKILL.md", "---\nid: demo.sample\n")
    with pytest.raises(SkillFormatError, match="unterminated"):
        load_library(tmp_path)


def test_department_mismatch_rejected(tmp_path: Path) -> None:
    content = VALID_SKILL.replace("department: demo", "department: recruiting")
    write_skill(tmp_path, "demo/sample/SKILL.md", content)
    with pytest.raises(SkillFormatError, match="does not match"):
        load_library(tmp_path)


def test_invalid_id_pattern_rejected(tmp_path: Path) -> None:
    content = VALID_SKILL.replace("id: demo.sample", "id: Demo Sample!")
    write_skill(tmp_path, "demo/sample/SKILL.md", content)
    with pytest.raises(SkillFormatError, match="invalid skill frontmatter"):
        load_library(tmp_path)


def test_unknown_frontmatter_field_rejected(tmp_path: Path) -> None:
    content = VALID_SKILL.replace("tags: [test]\n---", "tags: [test]\nunknown_field: oops\n---")
    write_skill(tmp_path, "demo/sample/SKILL.md", content)
    with pytest.raises(SkillFormatError, match="invalid skill frontmatter"):
        load_library(tmp_path)


def test_empty_agents_rejected(tmp_path: Path) -> None:
    content = VALID_SKILL.replace("agents: [test_agent]", "agents: []")
    write_skill(tmp_path, "demo/sample/SKILL.md", content)
    with pytest.raises(SkillFormatError):
        load_library(tmp_path)


def test_duplicate_skill_id_rejected(tmp_path: Path) -> None:
    write_skill(tmp_path, "demo/one/SKILL.md", VALID_SKILL)
    write_skill(tmp_path, "demo/two/SKILL.md", VALID_SKILL)
    with pytest.raises(SkillFormatError, match="duplicate skill id"):
        load_library(tmp_path)


def test_skill_must_live_under_department_and_domain_dir(tmp_path: Path) -> None:
    # one level too shallow: <root>/sample/SKILL.md instead of <root>/sample/<domain>/SKILL.md
    write_skill(tmp_path, "sample/SKILL.md", VALID_SKILL)
    with pytest.raises(SkillFormatError, match="must live under"):
        load_library(tmp_path)


def test_knowledge_documents_discovered(tmp_path: Path) -> None:
    write_skill(tmp_path, "demo/sample/SKILL.md", VALID_SKILL)
    write_skill(
        tmp_path,
        "demo/sample/knowledge/guide.md",
        "---\nid: guide\ntitle: A Guide\ntags: [how-to]\n---\n\nGuide content.",
    )
    skill = load_library(tmp_path)[0]

    assert len(skill.knowledge) == 1
    doc = skill.knowledge[0]
    assert doc.id == "guide"
    assert doc.namespace == "demo.sample"
    assert doc.department == "demo"
    assert skill.knowledge_namespaces == ["demo.sample"]


def test_duplicate_knowledge_id_rejected(tmp_path: Path) -> None:
    write_skill(tmp_path, "demo/sample/SKILL.md", VALID_SKILL)
    write_skill(tmp_path, "demo/sample/knowledge/a.md", "---\nid: same\n---\nA")
    write_skill(tmp_path, "demo/sample/knowledge/b.md", "---\nid: same\n---\nB")
    with pytest.raises(SkillFormatError, match="duplicate knowledge id"):
        load_library(tmp_path)


def test_content_hash_changes_with_body(tmp_path: Path) -> None:
    write_skill(tmp_path, "demo/sample/SKILL.md", VALID_SKILL)
    first = load_library(tmp_path)[0].content_hash

    changed = VALID_SKILL.replace("Do the thing carefully.", "Do the thing differently.")
    write_skill(tmp_path, "demo/sample/SKILL.md", changed)
    second = load_library(tmp_path)[0].content_hash

    assert first != second


def test_content_hash_stable_for_identical_content(tmp_path: Path) -> None:
    write_skill(tmp_path, "demo/sample/SKILL.md", VALID_SKILL)
    first = load_skill(tmp_path / "demo/sample/SKILL.md", root=tmp_path).content_hash
    second = load_skill(tmp_path / "demo/sample/SKILL.md", root=tmp_path).content_hash
    assert first == second


def test_fingerprint_covers_knowledge(tmp_path: Path) -> None:
    write_skill(tmp_path, "demo/sample/SKILL.md", VALID_SKILL)
    write_skill(tmp_path, "demo/sample/knowledge/guide.md", "---\nid: guide\n---\nOriginal.")
    before = library_fingerprint(load_library(tmp_path))

    write_skill(tmp_path, "demo/sample/knowledge/guide.md", "---\nid: guide\n---\nChanged.")
    after = library_fingerprint(load_library(tmp_path))

    assert before != after


def test_discover_requires_existing_root(tmp_path: Path) -> None:
    with pytest.raises(SkillFormatError, match="does not exist"):
        discover_skill_paths(tmp_path / "missing")


def test_repo_library_loads_and_is_valid() -> None:
    """The repository's own skills/ directory must always be valid."""
    skills = load_library(SKILLS_ROOT)

    assert len(skills) >= 5
    ids = {skill.id for skill in skills}
    assert "recruiting.screening" in ids
    assert "recruiting.evaluation" in ids
    assert "recruiting.feedback" in ids
    assert "platform.compliance" in ids
    assert "platform.knowledge" in ids

    for skill in skills:
        assert len(skill.instructions) > 100
        assert skill.manifest.agents, f"{skill.id} must declare agents"
        assert len(skill.content_hash) == 64


def test_repo_knowledge_namespaces() -> None:
    skills = load_library(SKILLS_ROOT)
    namespaces = {doc.namespace for skill in skills for doc in skill.knowledge}

    assert "recruiting.evaluation" in namespaces
    assert "recruiting.feedback" in namespaces
    assert "platform.compliance" in namespaces
    assert "platform.knowledge" in namespaces
