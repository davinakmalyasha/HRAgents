from pathlib import Path

import pytest

from hr_agents.knowledge import KnowledgeRetriever
from hr_agents.services.audit import AuditChain
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.tools import ToolRegistry, make_canonicalize_skill_tool, make_search_knowledge_tool

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


@pytest.fixture
async def scoped_tools() -> ToolRegistry:
    registry = SkillRegistry(load_library(SKILLS_ROOT))
    retriever = await KnowledgeRetriever.build(
        registry.knowledge(), allowed_namespaces=["recruiting.evaluation", "platform.compliance"]
    )
    tools = ToolRegistry(audit=AuditChain())
    tools.register(make_search_knowledge_tool(retriever, namespaces=["recruiting.evaluation"]))
    tools.register(make_canonicalize_skill_tool())
    return tools


async def test_search_knowledge_returns_citations(scoped_tools: ToolRegistry) -> None:
    result = await scoped_tools.execute(
        agent_name="resume_deconstructor",
        tool_name="search_knowledge",
        arguments={"query": "systems literacy architecture"},
    )

    assert result["count"] >= 1
    hit = result["results"][0]
    assert hit["citation"]
    assert hit["doc_id"]
    assert "text" in hit


async def test_search_knowledge_empty_query(scoped_tools: ToolRegistry) -> None:
    result = await scoped_tools.execute(
        agent_name="resume_deconstructor",
        tool_name="search_knowledge",
        arguments={"query": "   "},
    )
    assert result["results"] == []
    assert "error" in result


async def test_search_knowledge_limit_capped(scoped_tools: ToolRegistry) -> None:
    result = await scoped_tools.execute(
        agent_name="resume_deconstructor",
        tool_name="search_knowledge",
        arguments={"query": "engineer", "limit": 1000},
    )
    assert len(result["results"]) <= 10


async def test_search_knowledge_respects_scope(scoped_tools: ToolRegistry) -> None:
    result = await scoped_tools.execute(
        agent_name="resume_deconstructor",
        tool_name="search_knowledge",
        arguments={"query": "consent UU PDP personal data"},
    )
    assert all(hit["namespace"] == "recruiting.evaluation" for hit in result["results"])


async def test_search_knowledge_permission_enforced(scoped_tools: ToolRegistry) -> None:
    from hr_agents.tools import ToolPermissionError

    with pytest.raises(ToolPermissionError):
        await scoped_tools.execute(
            agent_name="unknown_agent",
            tool_name="search_knowledge",
            arguments={"query": "anything"},
        )


async def test_canonicalize_skill_normalizes_aliases(scoped_tools: ToolRegistry) -> None:
    result = await scoped_tools.execute(
        agent_name="resume_deconstructor",
        tool_name="canonicalize_skill",
        arguments={"skill_name": "Postgres"},
    )
    assert result == {"input": "Postgres", "canonical": "postgresql"}


async def test_canonicalize_skill_permission(scoped_tools: ToolRegistry) -> None:
    from hr_agents.tools import ToolPermissionError

    with pytest.raises(ToolPermissionError):
        await scoped_tools.execute(
            agent_name="screening_coordinator",
            tool_name="canonicalize_skill",
            arguments={"skill_name": "K8s"},
        )


async def test_tool_calls_land_on_audit_chain(scoped_tools: ToolRegistry) -> None:
    await scoped_tools.execute(
        agent_name="resume_deconstructor",
        tool_name="canonicalize_skill",
        arguments={"skill_name": "py"},
    )
    audit: AuditChain = scoped_tools._audit  # type: ignore[assignment]
    assert audit.verify() == -1
    assert audit.entries[-1].action == "tool.canonicalize_skill"
