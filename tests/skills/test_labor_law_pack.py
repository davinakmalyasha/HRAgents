"""Statutory knowledge pack: every note sourced, figure-free, retrievable."""

import re
from pathlib import Path

import yaml

from hr_agents.knowledge import KnowledgeRetriever
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.workspaces import WorkspaceId, default_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"
PACK_DIR = SKILLS_ROOT / "platform" / "labor-law" / "knowledge"

EXPECTED_IDS = frozenset(
    {
        "annual-leave",
        "sick-leave",
        "izin-personal",
        "maternity-leave",
        "public-holidays",
        "probation-pkwt",
        "working-time-overtime",
        "thr-timing",
        "bpjs-structure",
        "pph21-structure",
        "minimum-wage",
        "termination-final-pay",
    }
)

FORBIDDEN = [
    re.compile(pattern)
    for pattern in (
        r"Rp\b",
        r"\bIDR\b",
        r"%",
        "\u00d7",
        r"\b\d+(?:\.\d+)?\s*x\b",
        r"\bpersen\b",
        r"\bpercent\b",
        r"\bkali lipat\b",
    )
]


def _read_pack() -> dict[str, tuple[dict, str]]:
    """Raw frontmatter and body per knowledge file, without the skill loader."""
    docs: dict[str, tuple[dict, str]] = {}
    for path in sorted(PACK_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        _, raw, body = text.lstrip().split("---", 2)
        meta = yaml.safe_load(raw)
        assert isinstance(meta, dict), f"{path}: frontmatter must be a mapping"
        docs[path.stem] = (meta, body.strip())
    return docs


def test_pack_manifest_names_the_agent_and_nothing_else() -> None:
    skills = {skill.id: skill for skill in load_library(SKILLS_ROOT)}
    skill = skills["platform.labor-law"]

    assert skill.manifest.department == "platform"
    assert skill.manifest.agents == ["policy_assistant"]
    assert skill.knowledge_namespaces == ["platform.labor-law"]


def test_all_twelve_notes_present_with_stable_ids() -> None:
    docs = _read_pack()

    assert set(docs) == EXPECTED_IDS
    for stem, (meta, _) in docs.items():
        assert meta.get("id", stem) == stem, f"{stem}: filename and id disagree"


def test_every_note_names_its_source_and_freshness() -> None:
    for stem, (meta, body) in _read_pack().items():
        assert str(meta.get("source", "")).strip(), f"{stem}: frontmatter needs a source"
        assert str(meta.get("verified_on", "")).strip(), (
            f"{stem}: frontmatter needs a verified_on date"
        )
        assert "Source:" in body, f"{stem}: body must carry a Source line"
        assert "operator" in body.lower(), (
            f"{stem}: body must point at the operator table or policy holding figures"
        )


def test_no_money_percent_or_multiplier_figures() -> None:
    """Rates live in verified tables, never in prose. A figure here is a second
    source of truth that rots the moment a decree changes."""
    for stem, (meta, body) in _read_pack().items():
        text = yaml.safe_dump(meta) + "\n" + body
        for pattern in FORBIDDEN:
            assert not pattern.search(text), (
                f"{stem}: forbidden figure {pattern.pattern!r} — "
                "money, shares and multipliers belong in rate tables"
            )


async def test_labor_question_retrieves_the_pack() -> None:
    registry = SkillRegistry(load_library(SKILLS_ROOT))
    retriever = await KnowledgeRetriever.build(registry.knowledge())

    hits = await retriever.retrieve("cuti tahunan berapa hari", namespaces=["platform.labor-law"])

    assert hits
    assert all(hit.namespace == "platform.labor-law" for hit in hits)
    assert "annual-leave" in {hit.doc_id for hit in hits[:3]}
    assert all(hit.citation() for hit in hits)


async def test_policy_workspace_claims_the_pack() -> None:
    definition = default_registry().get(WorkspaceId.POLICY)

    assert "platform.labor-law" in definition.knowledge_namespaces
