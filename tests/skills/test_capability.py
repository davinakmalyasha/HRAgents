from pathlib import Path

from pydantic_ai.capabilities import Capability

from hr_agents.skills import build_capability, load_library
from hr_agents.skills.capability import build_capabilities

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


def test_build_capability_maps_fields() -> None:
    skill = next(s for s in load_library(SKILLS_ROOT) if s.id == "recruiting.screening")
    capability = build_capability(skill)

    assert isinstance(capability, Capability)
    assert capability.id == "recruiting.screening"
    assert capability.description == skill.manifest.description
    assert capability.defer_loading is True


def test_build_capabilities_for_all_skills() -> None:
    skills = load_library(SKILLS_ROOT)
    capabilities = build_capabilities(skills)

    assert len(capabilities) == len(skills)
    assert {capability.id for capability in capabilities} == {skill.id for skill in skills}


def test_build_capabilities_with_tools_mapping() -> None:
    skills = load_library(SKILLS_ROOT)

    def sample_tool(topic: str) -> str:
        """A sample tool."""
        return topic

    capabilities = build_capabilities(
        skills, tools_by_skill={"recruiting.screening": [sample_tool]}
    )
    assert len(capabilities) == len(skills)


def test_defer_loading_can_be_disabled(tmp_path: Path) -> None:
    skill_path = tmp_path / "demo" / "always" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\n"
        "id: demo.always\n"
        "name: Always On\n"
        "description: Always in the system prompt.\n"
        "department: demo\n"
        "agents: [demo_agent]\n"
        "defer_loading: false\n"
        "---\n\nAlways present instructions.",
        encoding="utf-8",
    )
    skill = load_library(tmp_path)[0]
    capability = build_capability(skill)
    assert capability.defer_loading is False
