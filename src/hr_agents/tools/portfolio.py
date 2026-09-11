"""Portfolio evaluation tools: GitHub, static analysis, publications, credentials."""

from __future__ import annotations

from pathlib import Path

from hr_agents.models import VerificationStatus
from hr_agents.services.ast_analysis import (
    AnalysisError,
    UnsafePathError,
    analyze_repository,
)
from hr_agents.services.github import GitHubClient
from hr_agents.tools.registry import ToolDefinition

_PORTFOLIO_AGENTS = frozenset({"code_portfolio"})


def make_github_profile_tool(client: GitHubClient) -> ToolDefinition:
    """List a candidate's public repositories with normalized facts."""

    async def github_profile(username: str, limit: int = 10) -> dict[str, object]:
        """Fetch public repositories for a GitHub username (most-starred first)."""
        if not username.strip():
            return {"error": "username must not be empty", "repos": []}
        effective_limit = max(1, min(limit, 20))
        repos = await client.list_repos(username.strip(), limit=effective_limit)
        return {
            "username": username.strip(),
            "count": len(repos),
            "repos": [
                {
                    "name": repo.name,
                    "full_name": repo.full_name,
                    "url": repo.url,
                    "description": repo.description,
                    "primary_language": repo.primary_language,
                    "stars": repo.stars,
                    "forks": repo.forks,
                    "is_fork": repo.is_fork,
                    "archived": repo.archived,
                    "has_tests": repo.has_tests_manifest,
                    "has_ci": repo.has_ci_config,
                    "last_commit_at": repo.last_commit_at.isoformat()
                    if repo.last_commit_at
                    else None,
                    "commits_last_90_days": repo.commits_last_90_days,
                }
                for repo in repos
            ],
        }

    return ToolDefinition(
        name="github_profile",
        description=(
            "Fetch a candidate's public GitHub repositories with stars, languages, "
            "activity, and CI/test signals. Use before analyzing individual repos."
        ),
        allowed_agents=_PORTFOLIO_AGENTS,
        handler=github_profile,
        tags=frozenset({"github", "read", "external"}),
    )


def make_repo_metrics_tool(client: GitHubClient) -> ToolDefinition:
    """Detailed facts for one repository."""

    async def repo_metrics(full_name: str) -> dict[str, object]:
        """Fetch detailed metrics for one repository by 'owner/name'."""
        repo = await client.repo_info(full_name.strip())
        if repo is None:
            return {"error": f"repository not found: {full_name}", "repo": None}
        return {
            "repo": {
                "name": repo.name,
                "full_name": repo.full_name,
                "url": repo.url,
                "primary_language": repo.primary_language,
                "languages": repo.languages,
                "stars": repo.stars,
                "forks": repo.forks,
                "is_fork": repo.is_fork,
                "archived": repo.archived,
                "has_readme": repo.has_readme,
                "has_tests": repo.has_tests_manifest,
                "has_ci": repo.has_ci_config,
                "license": repo.license,
                "total_commits": repo.total_commits,
                "commits_last_90_days": repo.commits_last_90_days,
            }
        }

    return ToolDefinition(
        name="repo_metrics",
        description="Fetch detailed metrics for one repository (owner/name).",
        allowed_agents=_PORTFOLIO_AGENTS,
        handler=repo_metrics,
        tags=frozenset({"github", "read", "external"}),
    )


def make_analyze_repo_ast_tool(analysis_root: Path) -> ToolDefinition:
    """Static analysis of a locally available repository checkout."""

    def analyze_repo_ast(repo_path: str) -> dict[str, object]:
        """Run complexity and structure analysis on a local repository path.

        Path is resolved against the configured analysis root; anything that
        escapes it is refused.
        """
        from hr_agents.services.ast_analysis import resolve_repo_path

        try:
            resolved = resolve_repo_path(repo_path, root=analysis_root)
            analysis = analyze_repository(resolved)
        except UnsafePathError as exc:
            return {"error": str(exc)}
        except AnalysisError as exc:
            return {"error": str(exc)}

        return {
            "path": str(repo_path),
            "functions_analyzed": analysis.complexity.functions_analyzed,
            "avg_cyclomatic_complexity": analysis.complexity.avg_complexity,
            "max_cyclomatic_complexity": analysis.complexity.max_complexity,
            "avg_function_length": analysis.complexity.avg_function_length,
            "files_analyzed": analysis.complexity.files_analyzed,
            "files_skipped": analysis.complexity.files_skipped,
            "has_tests": analysis.has_tests,
            "has_ci": analysis.has_ci,
            "has_readme": analysis.has_readme,
            "frameworks": analysis.frameworks,
            "languages": analysis.languages,
        }

    return ToolDefinition(
        name="analyze_repo_ast",
        description=(
            "Analyze a local repository checkout: cyclomatic complexity, function "
            "length, test/CI presence, frameworks, and language mix. Path must be "
            "inside the configured analysis root."
        ),
        allowed_agents=_PORTFOLIO_AGENTS,
        handler=analyze_repo_ast,
        tags=frozenset({"ast", "read", "deterministic"}),
    )


def make_detect_frameworks_tool(analysis_root: Path) -> ToolDefinition:
    """Manifest-based framework detection for a local repository."""

    def detect_frameworks(repo_path: str) -> dict[str, object]:
        """Detect frameworks from manifest files (requirements, package.json, go.mod)."""
        from hr_agents.services.ast_analysis import (
            detect_frameworks as detect,
        )
        from hr_agents.services.ast_analysis import resolve_repo_path

        try:
            resolved = resolve_repo_path(repo_path, root=analysis_root)
        except (UnsafePathError, AnalysisError) as exc:
            return {"error": str(exc)}
        return {"path": str(repo_path), "frameworks": detect(resolved)}

    return ToolDefinition(
        name="detect_frameworks",
        description=(
            "Detect technologies and frameworks from a local repository's manifest "
            "files. Deterministic; no network."
        ),
        allowed_agents=_PORTFOLIO_AGENTS,
        handler=detect_frameworks,
        tags=frozenset({"ast", "read", "deterministic"}),
    )


def make_verify_credential_tool(known_credentials: dict[str, str] | None = None) -> ToolDefinition:
    """Credential verification against a local registry snapshot.

    The registry maps credential_id → status ('verified', 'failed', 'expired').
    Live issuer APIs plug in later; the tool contract stays the same.
    """
    registry = {key.lower(): value for key, value in (known_credentials or {}).items()}

    def verify_credential(credential_id: str) -> dict[str, object]:
        """Check a credential ID against the verification registry."""
        value = registry.get(credential_id.strip().lower())
        if value is None:
            return {
                "credential_id": credential_id,
                "status": VerificationStatus.UNVERIFIED.value,
                "detail": "not present in the verification registry",
            }
        return {"credential_id": credential_id, "status": value, "detail": "registry match"}

    return ToolDefinition(
        name="verify_credential",
        description=(
            "Verify a professional credential ID against the issuer registry. "
            "Returns verified / failed / expired / unverified."
        ),
        allowed_agents=_PORTFOLIO_AGENTS,
        handler=verify_credential,
        tags=frozenset({"credentials", "read"}),
    )


def make_lookup_publication_tool(
    known_dois: dict[str, dict[str, object]] | None = None,
) -> ToolDefinition:
    """Publication lookup against a local Crossref-style snapshot.

    Live Crossref/ORCID/arXiv adapters plug in later behind the same contract.
    """
    index = {key.lower(): value for key, value in (known_dois or {}).items()}

    def lookup_publication(doi: str) -> dict[str, object]:
        """Look up a publication by DOI; returns verification and citation data."""
        normalized = doi.strip().lower()
        record = index.get(normalized)
        if record is None:
            return {
                "doi": doi,
                "status": VerificationStatus.UNVERIFIED.value,
                "detail": "DOI not found in the reference index",
            }
        return {
            "doi": doi,
            "status": VerificationStatus.VERIFIED.value,
            "title": record.get("title"),
            "year": record.get("year"),
            "venue": record.get("venue"),
            "citation_count": record.get("citation_count"),
        }

    return ToolDefinition(
        name="lookup_publication",
        description=(
            "Verify a publication DOI and return bibliographic details with citation count."
        ),
        allowed_agents=_PORTFOLIO_AGENTS,
        handler=lookup_publication,
        tags=frozenset({"publications", "read"}),
    )
