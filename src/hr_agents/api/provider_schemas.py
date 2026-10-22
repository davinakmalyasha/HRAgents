"""Request/response schemas for the read-only provider status surface."""

from __future__ import annotations

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.providers.base import Capability, ProviderHealthStatus


class ProviderStatusView(StrictModel):
    """What one capability is wired to, and whether it answers.

    ``config`` is masked: a secret is shown as its last four characters and
    nothing else, because this view is an operator's troubleshooting aid, not
    a place to read a key out of the database.
    """

    capability: Capability
    provider_id: str
    display_name: str
    status: ProviderHealthStatus
    detail: str
    locked: bool
    source: str
    requires_network: bool
    docs_url: str | None = None
    config: dict[str, object] = Field(default_factory=dict)
