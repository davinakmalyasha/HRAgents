from pathlib import Path

import pytest

from hr_agents.models import VerificationStatus
from hr_agents.services.audit import AuditChain
from hr_agents.services.github import FixtureGitHubClient, GitHubRepoInfo
from hr_agents.tools import (
    ToolRegistry,
    make_analyze_repo_ast_tool,
    make_detect_frameworks_tool,
    make_github_profile_tool,
    make_lookup_publication_tool,
    make_repo_metrics_tool,
    make_verify_credential_tool,
)


def sample_repos() -> dict[str, list[GitHubRepoInfo]]:
    return {
        "budisantoso": [
            GitHubRepoInfo(
                name="payment-service",
                full_name="budisantoso/payment-service",
                url="https://github.com/budisantoso/payment-service",
                primary_language="Python",
                languages={"Python": 0.9, "Shell": 0.1},
                stars=42,
                forks=3,
                has_readme=True,
                has_tests_manifest=True,
                has_ci_config=True,
                commits_last_90_days=37,
            ),
            GitHubRepoInfo(
                name="old-fork",
                full_name="budisantoso/old-fork",
                is_fork=True,
                stars=0,
            ),
        ]
    }


@pytest.fixture
def registry(tmp_path: Path) -> ToolRegistry:
    tools = ToolRegistry(audit=AuditChain())
    client = FixtureGitHubClient(sample_repos())

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("fastapi\npydantic\n", encoding="utf-8")

    tools.register(make_github_profile_tool(client))
    tools.register(make_repo_metrics_tool(client))
    tools.register(make_analyze_repo_ast_tool(tmp_path))
    tools.register(make_detect_frameworks_tool(tmp_path))
    tools.register(make_verify_credential_tool({"aws-sa-12345": "verified", "bad-cert": "failed"}))
    tools.register(
        make_lookup_publication_tool(
            {"10.1234/example": {"title": "Queue Systems", "year": 2024, "citation_count": 9}}
        )
    )
    return tools


async def test_github_profile_lists_repos(registry: ToolRegistry) -> None:
    result = await registry.execute(
        agent_name="code_portfolio",
        tool_name="github_profile",
        arguments={"username": "budisantoso"},
    )
    assert result["count"] == 2
    top = result["repos"][0]
    assert top["name"] == "payment-service"
    assert top["commits_last_90_days"] == 37


async def test_github_profile_empty_username(registry: ToolRegistry) -> None:
    result = await registry.execute(
        agent_name="code_portfolio", tool_name="github_profile", arguments={"username": "  "}
    )
    assert result["repos"] == []
    assert "error" in result


async def test_repo_metrics_found_and_missing(registry: ToolRegistry) -> None:
    found = await registry.execute(
        agent_name="code_portfolio",
        tool_name="repo_metrics",
        arguments={"full_name": "budisantoso/payment-service"},
    )
    assert found["repo"]["stars"] == 42

    missing = await registry.execute(
        agent_name="code_portfolio",
        tool_name="repo_metrics",
        arguments={"full_name": "nobody/nothing"},
    )
    assert missing["repo"] is None
    assert "error" in missing


async def test_analyze_repo_ast(registry: ToolRegistry) -> None:
    result = await registry.execute(
        agent_name="code_portfolio",
        tool_name="analyze_repo_ast",
        arguments={"repo_path": "repo"},
    )
    assert result["functions_analyzed"] == 1
    assert result["frameworks"] == ["fastapi", "pydantic"]


async def test_analyze_repo_ast_blocks_escape(tmp_path: Path, registry: ToolRegistry) -> None:
    outside = tmp_path.parent / "outside-escape"
    outside.mkdir(exist_ok=True)
    result = await registry.execute(
        agent_name="code_portfolio",
        tool_name="analyze_repo_ast",
        arguments={"repo_path": str(outside)},
    )
    assert "escapes" in result["error"]


async def test_detect_frameworks_tool(registry: ToolRegistry) -> None:
    result = await registry.execute(
        agent_name="code_portfolio",
        tool_name="detect_frameworks",
        arguments={"repo_path": "repo"},
    )
    assert result["frameworks"] == ["fastapi", "pydantic"]


async def test_verify_credential_statuses(registry: ToolRegistry) -> None:
    verified = await registry.execute(
        agent_name="code_portfolio",
        tool_name="verify_credential",
        arguments={"credential_id": "AWS-SA-12345"},
    )
    assert verified["status"] == VerificationStatus.VERIFIED.value

    failed = await registry.execute(
        agent_name="code_portfolio",
        tool_name="verify_credential",
        arguments={"credential_id": "bad-cert"},
    )
    assert failed["status"] == VerificationStatus.FAILED.value

    unknown = await registry.execute(
        agent_name="code_portfolio",
        tool_name="verify_credential",
        arguments={"credential_id": "who-knows"},
    )
    assert unknown["status"] == VerificationStatus.UNVERIFIED.value


async def test_lookup_publication(registry: ToolRegistry) -> None:
    verified = await registry.execute(
        agent_name="code_portfolio",
        tool_name="lookup_publication",
        arguments={"doi": "10.1234/example"},
    )
    assert verified["status"] == VerificationStatus.VERIFIED.value
    assert verified["citation_count"] == 9

    unknown = await registry.execute(
        agent_name="code_portfolio",
        tool_name="lookup_publication",
        arguments={"doi": "10.9999/missing"},
    )
    assert unknown["status"] == VerificationStatus.UNVERIFIED.value


async def test_portfolio_tools_permission_denied(registry: ToolRegistry) -> None:
    from hr_agents.tools import ToolPermissionError

    with pytest.raises(ToolPermissionError):
        await registry.execute(
            agent_name="screening_coordinator",
            tool_name="github_profile",
            arguments={"username": "x"},
        )
