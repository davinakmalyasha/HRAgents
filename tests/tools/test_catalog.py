"""Tool catalog and workspace pack consistency.

The catalog is the canonical inventory of governed tool names; these tests make
pack drift (typo'd tools, stale agent names, grants outside a workspace's tool
scope) fail the gate instead of silently granting or hiding capabilities.
"""

from pathlib import Path

from hr_agents.agents import AGENT_NAMES
from hr_agents.knowledge import KnowledgeRetriever
from hr_agents.services.github import GitHubRepoInfo
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.tools import (
    TOOL_NAMES,
    ToolRegistry,
    make_analyze_repo_ast_tool,
    make_canonicalize_skill_tool,
    make_capture_consent_tool,
    make_detect_frameworks_tool,
    make_escalate_to_human_tool,
    make_get_candidate_profile_tool,
    make_get_evaluation_breakdown_tool,
    make_github_profile_tool,
    make_lookup_publication_tool,
    make_record_availability_tool,
    make_repo_metrics_tool,
    make_search_knowledge_tool,
    make_verify_credential_tool,
)
from hr_agents.workspaces import default_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


class FakeGitHubClient:
    async def list_repos(self, username: str, *, limit: int = 10) -> list[GitHubRepoInfo]:
        return []

    async def repo_info(self, full_name: str) -> GitHubRepoInfo | None:
        return None


async def build_full_registry() -> ToolRegistry:
    skills = SkillRegistry(load_library(SKILLS_ROOT))
    retriever = await KnowledgeRetriever.build(skills.knowledge())
    registry = ToolRegistry()
    registry.register(make_search_knowledge_tool(retriever, namespaces=["platform.knowledge"]))
    registry.register(make_canonicalize_skill_tool())
    registry.register(make_capture_consent_tool(lambda *_: {}))
    registry.register(make_record_availability_tool(lambda *_: {}))
    registry.register(make_escalate_to_human_tool(lambda *_: {}))
    registry.register(make_get_candidate_profile_tool(lambda _: None))
    registry.register(make_get_evaluation_breakdown_tool(lambda _: None))
    registry.register(make_github_profile_tool(FakeGitHubClient()))
    registry.register(make_repo_metrics_tool(FakeGitHubClient()))
    registry.register(make_analyze_repo_ast_tool(Path(".")))
    registry.register(make_detect_frameworks_tool(Path(".")))
    registry.register(make_verify_credential_tool())
    registry.register(make_lookup_publication_tool())
    return registry


async def test_catalog_matches_registered_tools() -> None:
    registry = await build_full_registry()
    assert set(registry.names()) == TOOL_NAMES


async def test_workspace_packs_reference_known_tools_and_agents() -> None:
    registry = await build_full_registry()
    registry_names = set(registry.names())

    for pack in default_registry().list_all():
        assert pack.tools <= registry_names, pack.id
        assert pack.agents <= AGENT_NAMES, pack.id

        for agent in pack.agents:
            granted = set(registry.names_for(agent))
            assert granted <= pack.tools, (pack.id, agent, granted - pack.tools)
