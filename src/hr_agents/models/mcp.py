"""Operator configuration for external MCP servers.

Only HTTP/SSE servers are accepted. A stdio server would mean spawning a
process, and this product's hard rule is that agents never get a shell; the
transport choice is the enforcement, not a preference.

Tool exposure is explicit: the operator lists the remote tools and classifies
each as read, write or destructive. A tool the server offers but the config does
not name is **not registered**, so a new server-side tool cannot quietly widen
what an agent can do.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from hr_agents.models.common import StrictModel, UtcDateTime

McpImpact = Literal["read", "write", "destructive"]


class McpServerConfig(StrictModel):
    """One operator-approved MCP server and the tools it may expose."""

    name: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        max_length=40,
        description="Short identifier used in tool names: mcp.<name>.<tool>.",
    )
    url: str = Field(
        min_length=1,
        max_length=500,
        description="HTTP(S) streamable endpoint. Credentials never belong in the URL.",
    )
    auth_env: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Name of the environment variable holding a bearer token. The token "
            "itself is never in configuration, logs or API responses."
        ),
    )
    timeout_seconds: float = Field(default=10.0, gt=0.0, le=120.0)
    allowed_agents: list[str] = Field(
        default_factory=list,
        description=(
            "Agents permitted to call these tools. Empty registers the tools but "
            "lets no agent use them — discovery without exposure."
        ),
    )
    tools: dict[str, McpImpact] = Field(
        default_factory=dict,
        description=(
            "Remote tool name → impact. Only these tools are registered; an "
            "unlisted tool stays invisible to every agent."
        ),
    )

    @model_validator(mode="after")
    def _validate_endpoint(self) -> McpServerConfig:
        if not self.url.startswith(("https://", "http://")):
            raise ValueError("an MCP endpoint must start with https:// or http://")
        if self.url.startswith("http://") and not (
            self.url.startswith("http://localhost") or self.url.startswith("http://127.0.0.1")
        ):
            raise ValueError("plain HTTP is only allowed for localhost development")
        if "@" in self.url.split("://", 1)[1].split("/", 1)[0]:
            raise ValueError("the endpoint must not embed credentials; use auth_env instead")
        return self


class McpServerStatus(StrictModel):
    """What the operator sees about one server: reachable or not, and which tools."""

    name: str
    url: str
    connected: bool
    detail: str = ""
    tools: list[str] = Field(default_factory=list)
    tool_count: int = 0


class McpServerDefinition(StrictModel):
    """A dashboard-managed server configuration, with its last editor.

    Stored globally: MCP connections and their tools are installed into one
    process-wide registry, so they are an install capability rather than a
    tenant's data. The environment's list remains the operator's floor;
    dashboards may add servers but not shadow an environment name.
    """

    config: McpServerConfig
    updated_by: str = Field(min_length=1, max_length=200)
    updated_at: UtcDateTime


class McpProbeResult(StrictModel):
    """The answer to a Test click: reachable or not, and the tools it offers."""

    name: str
    connected: bool
    detail: str = ""
    tools: list[str] = Field(default_factory=list)


class McpServerCatalogEntry(StrictModel):
    """A connector template: shape, data flow and enablement, never a connection."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    data_flow: str = Field(min_length=1, max_length=1000)
    scopes: list[str] = Field(default_factory=list)
    auth_env: str = Field(min_length=1, max_length=100)
    auth_hint: str = Field(min_length=1, max_length=500)
    tools: dict[str, McpImpact] = Field(default_factory=dict)
    allowed_agents: list[str] = Field(default_factory=list)
    enable_steps: list[str] = Field(default_factory=list)
