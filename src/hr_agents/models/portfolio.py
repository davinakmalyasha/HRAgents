"""Portfolio evidence models — output of the Code & Portfolio Evaluation agent."""

from __future__ import annotations

from pydantic import Field

from hr_agents.models.common import (
    EvidenceRef,
    StrictModel,
    UtcDateTime,
    VerificationStatus,
    utc_now,
)


class RepoEvidence(StrictModel):
    """Structured evidence for one repository."""

    name: str = Field(min_length=1)
    url: str | None = None
    primary_language: str | None = None
    languages: dict[str, float] = Field(default_factory=dict)
    stars: int = Field(default=0, ge=0)
    forks: int = Field(default=0, ge=0)
    is_fork: bool = False
    archived: bool = False
    has_readme: bool = False
    has_tests: bool = False
    has_ci: bool = False
    license: str | None = None
    last_commit_at: UtcDateTime | None = None
    commits_last_90_days: int = Field(default=0, ge=0)
    total_commits: int = Field(default=0, ge=0)
    frameworks: list[str] = Field(default_factory=list)
    avg_cyclomatic_complexity: float | None = Field(default=None, ge=0)
    max_cyclomatic_complexity: float | None = Field(default=None, ge=0)
    functions_analyzed: int = Field(default=0, ge=0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PublicationEvidence(StrictModel):
    """A publication with verification status."""

    title: str = Field(min_length=1)
    doi: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)
    venue: str | None = None
    citation_count: int | None = Field(default=None, ge=0)
    status: VerificationStatus = VerificationStatus.CLAIMED
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CredentialEvidence(StrictModel):
    """A professional credential with verification status."""

    name: str = Field(min_length=1)
    issuer: str | None = None
    credential_id: str | None = None
    status: VerificationStatus = VerificationStatus.CLAIMED
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PortfolioSummary(StrictModel):
    """Aggregate numbers the deterministic scorer can consume."""

    public_repos: int = Field(default=0, ge=0)
    repos_with_tests: int = Field(default=0, ge=0)
    repos_with_ci: int = Field(default=0, ge=0)
    total_commits_last_90_days: int = Field(default=0, ge=0)
    distinct_frameworks: int = Field(default=0, ge=0)
    verified_publications: int = Field(default=0, ge=0)
    verified_credentials: int = Field(default=0, ge=0)
    avg_cyclomatic_complexity: float | None = Field(default=None, ge=0)


class PortfolioEvidence(StrictModel):
    """Full structured portfolio evidence for one candidate."""

    candidate_id: str | None = None
    github_username: str | None = None
    repos: list[RepoEvidence] = Field(default_factory=list)
    publications: list[PublicationEvidence] = Field(default_factory=list)
    credentials: list[CredentialEvidence] = Field(default_factory=list)
    summary: PortfolioSummary = Field(default_factory=PortfolioSummary)
    notes: list[str] = Field(default_factory=list)
    extracted_at: UtcDateTime = Field(default_factory=utc_now)

    def compute_summary(self) -> PortfolioSummary:
        """Recompute the summary deterministically from the evidence.

        Forks and archived repositories are excluded from aggregate signals:
        a fork's commits and dependencies are usually upstream work, not the
        candidate's.
        """
        active = [repo for repo in self.repos if not repo.is_fork and not repo.archived]

        frameworks: set[str] = set()
        for repo in active:
            frameworks.update(item.lower() for item in repo.frameworks)

        complexities = [
            repo.avg_cyclomatic_complexity
            for repo in active
            if repo.avg_cyclomatic_complexity is not None
        ]

        self.summary = PortfolioSummary(
            public_repos=len(active),
            repos_with_tests=sum(1 for repo in active if repo.has_tests),
            repos_with_ci=sum(1 for repo in active if repo.has_ci),
            total_commits_last_90_days=sum(repo.commits_last_90_days for repo in active),
            distinct_frameworks=len(frameworks),
            verified_publications=sum(
                1 for pub in self.publications if pub.status is VerificationStatus.VERIFIED
            ),
            verified_credentials=sum(
                1 for cred in self.credentials if cred.status is VerificationStatus.VERIFIED
            ),
            avg_cyclomatic_complexity=(
                round(sum(complexities) / len(complexities), 4) if complexities else None
            ),
        )
        return self.summary
