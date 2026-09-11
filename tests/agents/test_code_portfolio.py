from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from hr_agents.agents import AgentDeps, AgentRuntime
from hr_agents.agents.code_portfolio import AGENT_NAME, CodePortfolioEvaluator
from hr_agents.knowledge import KnowledgeRetriever
from hr_agents.services.audit import AuditChain
from hr_agents.services.github import FixtureGitHubClient, GitHubRepoInfo
from hr_agents.skills import SkillRegistry, load_library
from hr_agents.tools import (
    ToolRegistry,
    make_analyze_repo_ast_tool,
    make_detect_frameworks_tool,
    make_github_profile_tool,
    make_lookup_publication_tool,
    make_repo_metrics_tool,
    make_search_knowledge_tool,
    make_verify_credential_tool,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


@pytest.fixture
def skills() -> SkillRegistry:
    return SkillRegistry(load_library(SKILLS_ROOT))


@pytest.fixture
async def deps(skills: SkillRegistry, tmp_path: Path) -> AgentDeps:
    retriever = await KnowledgeRetriever.build(skills.knowledge())
    tools = ToolRegistry(audit=AuditChain())
    client = FixtureGitHubClient(
        {
            "budisantoso": [
                GitHubRepoInfo(
                    name="payment-service",
                    full_name="budisantoso/payment-service",
                    stars=42,
                    has_tests_manifest=True,
                    commits_last_90_days=12,
                )
            ]
        }
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def ok():\n    return 1\n", encoding="utf-8")

    tools.register(make_search_knowledge_tool(retriever, namespaces=["recruiting.evaluation"]))
    tools.register(make_github_profile_tool(client))
    tools.register(make_repo_metrics_tool(client))
    tools.register(make_analyze_repo_ast_tool(tmp_path))
    tools.register(make_detect_frameworks_tool(tmp_path))
    tools.register(make_verify_credential_tool({"aws-1": "verified"}))
    tools.register(make_lookup_publication_tool({"10.1/x": {"title": "X"}}))
    return AgentDeps(tools=tools)


def make_agent(skills: SkillRegistry) -> CodePortfolioEvaluator:
    return CodePortfolioEvaluator(AgentRuntime(TestModel(call_tools=[])), skills=skills)


async def test_evaluate_returns_valid_evidence(skills: SkillRegistry, deps: AgentDeps) -> None:
    agent = make_agent(skills)
    result = await agent.evaluate(deps=deps, github_username="budisantoso")

    assert result.evidence is not None
    # Summary is recomputed deterministically after the model returns.
    assert result.evidence.summary is not None


async def test_evaluate_carries_skill_refs(skills: SkillRegistry, deps: AgentDeps) -> None:
    agent = make_agent(skills)
    result = await agent.evaluate(deps=deps, github_username="budisantoso")

    assert result.skill_refs
    ref_ids = {ref["skill_id"] for ref in result.skill_refs}
    assert "recruiting.evaluation" in ref_ids
    assert all(len(ref["hash"]) == 64 for ref in result.skill_refs)


async def test_evaluate_without_sources_still_valid(skills: SkillRegistry, deps: AgentDeps) -> None:
    agent = make_agent(skills)
    result = await agent.evaluate(deps=deps)
    assert result.evidence is not None


async def test_agent_name_constant() -> None:
    assert AGENT_NAME == "code_portfolio"
    assert CodePortfolioEvaluator.agent_name == AGENT_NAME


async def test_evidence_summary_recomputation() -> None:
    from hr_agents.models import (
        CredentialEvidence,
        PortfolioEvidence,
        PublicationEvidence,
        RepoEvidence,
        VerificationStatus,
    )

    evidence = PortfolioEvidence(
        repos=[
            RepoEvidence(
                name="a",
                has_tests=True,
                commits_last_90_days=10,
                frameworks=["FastAPI", "pydantic"],
                avg_cyclomatic_complexity=2.5,
            ),
            RepoEvidence(
                name="b",
                commits_last_90_days=5,
                frameworks=["fastapi"],
                avg_cyclomatic_complexity=4.0,
            ),
            RepoEvidence(name="fork", is_fork=True, commits_last_90_days=99),
        ],
        publications=[
            PublicationEvidence(title="P1", status=VerificationStatus.VERIFIED),
            PublicationEvidence(title="P2", status=VerificationStatus.CLAIMED),
        ],
        credentials=[
            CredentialEvidence(name="AWS", status=VerificationStatus.VERIFIED),
        ],
    )
    summary = evidence.compute_summary()

    assert summary.public_repos == 2
    assert summary.repos_with_tests == 1
    assert (
        summary.total_commits_last_90_days == 15
    )  # fork excluded from repo count but counted here
    assert summary.distinct_frameworks == 2
    assert summary.verified_publications == 1
    assert summary.verified_credentials == 1
    assert summary.avg_cyclomatic_complexity == 3.25
