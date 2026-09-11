"""Skill discovery and loading.

Layout convention::

    skills/
      <department>/
        <domain>/
          SKILL.md              # YAML frontmatter + markdown runbook
          knowledge/            # RAG documents (optional)
            *.md                # YAML frontmatter (id, title, tags) + content

Rules enforced at load time:
- frontmatter must parse and validate against :class:`SkillManifest`
- ``manifest.department`` must equal the top-level directory name
- skill ids must be unique across the library
- knowledge ids must be unique within a skill
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

import yaml
from pydantic import ValidationError

from hr_agents.skills.models import KnowledgeDoc, LoadedSkill, SkillManifest

SKILL_FILENAME = "SKILL.md"
KNOWLEDGE_DIRNAME = "knowledge"


class SkillFormatError(ValueError):
    """Raised when a skill or knowledge file violates the format."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_frontmatter(text: str, *, source: Path) -> tuple[dict, str]:
    """Split a markdown document into (frontmatter dict, body)."""
    if not text.lstrip().startswith("---"):
        raise SkillFormatError(f"{source}: missing YAML frontmatter (file must start with '---')")
    normalized = text.lstrip()
    parts = normalized.split("---", 2)
    if len(parts) < 3:
        raise SkillFormatError(f"{source}: unterminated YAML frontmatter")
    _, raw_frontmatter, body = parts
    try:
        meta = yaml.safe_load(raw_frontmatter)
    except yaml.YAMLError as exc:
        raise SkillFormatError(f"{source}: invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise SkillFormatError(f"{source}: frontmatter must be a YAML mapping")
    return meta, body.strip()


def discover_skill_paths(root: Path) -> list[Path]:
    """Find every SKILL.md under ``root``, sorted for deterministic loads."""
    if not root.is_dir():
        raise SkillFormatError(f"skills root does not exist: {root}")
    return sorted(root.glob(f"**/{SKILL_FILENAME}"))


def _department_from_path(skill_path: Path, root: Path) -> str:
    relative = skill_path.relative_to(root)
    if len(relative.parts) < 3:
        raise SkillFormatError(
            f"{skill_path}: SKILL.md must live under skills/<department>/<domain>/"
        )
    return relative.parts[0]


def _load_knowledge(skill_path: Path, *, department: str, domain: str) -> list[KnowledgeDoc]:
    knowledge_dir = skill_path.parent / KNOWLEDGE_DIRNAME
    if not knowledge_dir.is_dir():
        return []

    docs: list[KnowledgeDoc] = []
    seen_ids: set[str] = set()
    for doc_path in sorted(knowledge_dir.glob("**/*.md")):
        meta, content = _parse_frontmatter(doc_path.read_text(encoding="utf-8"), source=doc_path)
        doc_id = str(meta.get("id", doc_path.stem)).strip()
        if doc_id in seen_ids:
            raise SkillFormatError(f"{doc_path}: duplicate knowledge id {doc_id!r}")
        seen_ids.add(doc_id)
        title = meta.get("title", doc_id.replace("-", " ").title())
        raw_tags = meta.get("tags", []) or []
        if not isinstance(raw_tags, list):
            raise SkillFormatError(f"{doc_path}: 'tags' must be a list")
        try:
            doc = KnowledgeDoc(
                id=doc_id,
                title=str(title),
                department=department,
                namespace=f"{department}.{domain}",
                tags=[str(tag).lower() for tag in raw_tags],
                source_path=str(doc_path),
                content=content,
                content_hash=_sha256(content),
            )
        except ValidationError as exc:
            raise SkillFormatError(f"{doc_path}: invalid knowledge frontmatter: {exc}") from exc
        docs.append(doc)
    return docs


def load_skill(skill_path: Path, *, root: Path) -> LoadedSkill:
    """Load and validate a single SKILL.md (plus its knowledge documents)."""
    meta, body = _parse_frontmatter(skill_path.read_text(encoding="utf-8"), source=skill_path)
    try:
        manifest = SkillManifest.model_validate(meta)
    except ValidationError as exc:
        raise SkillFormatError(f"{skill_path}: invalid skill frontmatter: {exc}") from exc

    expected_department = _department_from_path(skill_path, root)
    if manifest.department != expected_department:
        raise SkillFormatError(
            f"{skill_path}: department {manifest.department!r} does not match "
            f"directory {expected_department!r}"
        )

    domain = skill_path.parent.name
    knowledge = _load_knowledge(skill_path, department=manifest.department, domain=domain)

    return LoadedSkill(
        manifest=manifest,
        instructions=body,
        content_hash=_sha256(body),
        source_path=str(skill_path),
        knowledge=knowledge,
    )


def load_library(root: Path) -> list[LoadedSkill]:
    """Load every skill under ``root`` with cross-skill validation."""
    skills: list[LoadedSkill] = []
    seen: dict[str, str] = {}
    for skill_path in discover_skill_paths(root):
        skill = load_skill(skill_path, root=root)
        if skill.id in seen:
            raise SkillFormatError(
                f"{skill_path}: duplicate skill id {skill.id!r} "
                f"(already defined at {seen[skill.id]})"
            )
        seen[skill.id] = str(skill_path)
        skills.append(skill)
    return skills


def library_fingerprint(skills: Iterable[LoadedSkill]) -> str:
    """Deterministic fingerprint of the entire library (skills + knowledge).

    Recorded in run metadata so any evaluation can be traced to the exact
    skill content that produced it.
    """
    lines: list[str] = []
    for skill in sorted(skills, key=lambda item: item.id):
        lines.append(f"skill:{skill.id}:{skill.manifest.version}:{skill.content_hash}")
        for doc in sorted(skill.knowledge, key=lambda item: item.id):
            lines.append(f"doc:{skill.id}:{doc.id}:{doc.content_hash}")
    return _sha256("\n".join(lines))
