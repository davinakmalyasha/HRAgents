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
    editable: bool = Field(
        default=False,
        description=(
            "Whether the dashboard may change this capability. False when the "
            "environment locks it, or when no encryption key is configured."
        ),
    )


class ProviderField(StrictModel):
    """One config field, derived from the provider's own Pydantic model."""

    name: str
    title: str
    type: str
    required: bool
    secret: bool
    description: str = ""
    default: object | None = None


class ProviderOption(StrictModel):
    """A registered provider plus the form its config model describes."""

    provider_id: str
    display_name: str
    description: str
    docs_url: str | None = None
    requires_network: bool
    fields: list[ProviderField]


class ProviderOptionsView(StrictModel):
    """What the operator may choose for one capability, and why they cannot."""

    capability: Capability
    selected_provider_id: str | None
    source: str
    locked: bool
    editable: bool
    providers: list[ProviderOption]


class ProviderConfigureRequest(StrictModel):
    provider_id: str = Field(min_length=1, max_length=120)
    config: dict[str, object] = Field(default_factory=dict)


class ProviderConfigureView(StrictModel):
    """The saved selection, its current health, and when it takes effect."""

    status: ProviderStatusView
    restart_required: bool = Field(
        default=True,
        description=(
            "The stored selection resolves for every new resolution immediately, "
            "but services already built at startup (the model runtime, the queue) "
            "keep the provider they were constructed with until a restart."
        ),
    )


class ProviderTestRequest(StrictModel):
    provider_id: str = Field(min_length=1, max_length=120)
    config: dict[str, object] = Field(default_factory=dict)


class ProviderTestView(StrictModel):
    status: ProviderHealthStatus
    detail: str
