"""Request/response schemas for the first-run setup surface."""

from __future__ import annotations

from hr_agents.models import StrictModel


class SetupCounts(StrictModel):
    employees: int
    jobs: int
    onboarding_templates: int
    offboarding_templates: int
    rate_tables: int
    unverified_rate_tables: int


class SetupStatusView(StrictModel):
    """What a first-run dashboard needs to know, and nothing secret."""

    app_name: str
    operator_name: str
    timezone: str
    store_backend: str
    llm_model: str
    auth_configured: bool
    counts: SetupCounts


class StarterSeedView(StrictModel):
    created: list[str]
    skipped: list[str]
