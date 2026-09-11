"""GitHub evidence collection.

Two implementations behind one protocol:

- :class:`FixtureGitHubClient` — deterministic, offline, used in tests and demos.
- :class:`HttpGitHubClient` — real GitHub REST API (token optional; unauthenticated
  requests are heavily rate-limited, so tokens are recommended).

Agents never see the network details: tools receive whichever client is injected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import Field

from hr_agents.models import StrictModel

GITHUB_API = "https://api.github.com"


class GitHubRepoInfo(StrictModel):
    """Normalized repository facts (subset of the GitHub payload)."""

    name: str
    full_name: str = ""
    url: str | None = None
    description: str | None = None
    primary_language: str | None = None
    languages: dict[str, float] = Field(default_factory=dict)
    stars: int = Field(default=0, ge=0)
    forks: int = Field(default=0, ge=0)
    is_fork: bool = False
    archived: bool = False
    has_readme: bool = False
    has_tests_manifest: bool = False
    has_ci_config: bool = False
    license: str | None = None
    last_commit_at: datetime | None = None
    commits_last_90_days: int = Field(default=0, ge=0)
    total_commits: int = Field(default=0, ge=0)


@runtime_checkable
class GitHubClient(Protocol):
    """Minimal GitHub surface used by the portfolio tools."""

    async def list_repos(self, username: str, *, limit: int = 10) -> list[GitHubRepoInfo]: ...

    async def repo_info(self, full_name: str) -> GitHubRepoInfo | None: ...


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class FixtureGitHubClient:
    """Deterministic client backed by an in-memory fixture map."""

    def __init__(self, repos_by_user: dict[str, list[GitHubRepoInfo]] | None = None) -> None:
        self._by_user = repos_by_user or {}

    async def list_repos(self, username: str, *, limit: int = 10) -> list[GitHubRepoInfo]:
        repos = self._by_user.get(username, [])
        ordered = sorted(repos, key=lambda repo: (-repo.stars, repo.name.lower()))
        return ordered[:limit]

    async def repo_info(self, full_name: str) -> GitHubRepoInfo | None:
        for repos in self._by_user.values():
            for repo in repos:
                if repo.full_name == full_name:
                    return repo
        return None


class HttpGitHubClient:
    """Real GitHub REST client."""

    def __init__(self, token: str | None = None, *, timeout: float = 10.0) -> None:
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(base_url=GITHUB_API, headers=headers, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_repos(self, username: str, *, limit: int = 10) -> list[GitHubRepoInfo]:
        response = await self._client.get(
            f"/users/{username}/repos",
            params={"sort": "pushed", "per_page": min(limit, 100), "type": "owner"},
        )
        response.raise_for_status()
        payload: list[dict[str, Any]] = response.json()

        repos: list[GitHubRepoInfo] = []
        for item in payload:
            info = self._normalize(item)
            info = await self._enrich(info, item.get("full_name", ""))
            repos.append(info)
        return repos[:limit]

    async def repo_info(self, full_name: str) -> GitHubRepoInfo | None:
        response = await self._client.get(f"/repos/{full_name}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        item = response.json()
        return await self._enrich(self._normalize(item), full_name)

    # --- internals ------------------------------------------------------

    def _normalize(self, item: dict[str, Any]) -> GitHubRepoInfo:
        return GitHubRepoInfo(
            name=str(item.get("name", "")),
            full_name=str(item.get("full_name", "")),
            url=item.get("html_url"),
            description=item.get("description"),
            primary_language=item.get("language"),
            stars=int(item.get("stargazers_count") or 0),
            forks=int(item.get("forks_count") or 0),
            is_fork=bool(item.get("fork")),
            archived=bool(item.get("archived")),
            license=(item.get("license") or {}).get("spdx_id")
            if isinstance(item.get("license"), dict)
            else None,
            last_commit_at=_parse_iso(item.get("pushed_at")),
        )

    async def _enrich(self, info: GitHubRepoInfo, full_name: str) -> GitHubRepoInfo:
        if not full_name:
            return info

        languages: dict[str, float] = {}
        try:
            response = await self._client.get(f"/repos/{full_name}/languages")
            if response.status_code == 200:
                total = sum(response.json().values()) or 1
                languages = {
                    name: round(count / total, 4) for name, count in response.json().items()
                }
        except httpx.HTTPError:
            pass

        commits_last_90 = 0
        try:
            since = (datetime.now(UTC) - timedelta(days=90)).isoformat()
            response = await self._client.get(
                f"/repos/{full_name}/commits", params={"since": since, "per_page": 100}
            )
            if response.status_code == 200:
                commits_last_90 = len(response.json())
        except httpx.HTTPError:
            pass

        return info.model_copy(
            update={
                "languages": languages,
                "commits_last_90_days": commits_last_90,
            }
        )
