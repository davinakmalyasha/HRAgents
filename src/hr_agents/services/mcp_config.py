"""Operator-managed MCP connections: merge, persist, probe, reload.

The environment list is the floor. A dashboard row may add a server, but it
cannot shadow an environment-configured name: an operator who pinned a connector
in `HRAGENTS_MCP_SERVERS` should not be silently overridden by a form. Deleting
a dashboard row removes it; the environment row (if any) is untouched because
there is none under that name.

Reloading is explicit and in-process. A save or delete rebuilds the manager,
unregisters the previous tools and closes the old connections, because leaving
a deleted server's tools callable would make removal cosmetic.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Mapping
from typing import Any

from hr_agents.errors import DomainError
from hr_agents.identity import ActorRef
from hr_agents.models import (
    McpProbeResult,
    McpServerConfig,
    McpServerDefinition,
    utc_now,
)
from hr_agents.services.mcp_client import HttpMcpConnection, McpManager

ENV_SOURCE = "environment"
DASHBOARD_SOURCE = "dashboard"


class McpConfigError(DomainError, RuntimeError):
    """Raised for a refused configuration change."""


class McpConfigStore:
    """In-memory configurations keyed by server name; the DB adapter overrides."""

    def __init__(self) -> None:
        self._items: dict[str, McpServerDefinition] = {}

    def list_all(self) -> list[McpServerDefinition]:
        return sorted(self._items.values(), key=lambda item: item.config.name)

    def upsert(self, definition: McpServerDefinition) -> None:
        self._items[definition.config.name] = definition

    def delete(self, name: str) -> bool:
        return self._items.pop(name, None) is not None


async def probe_mcp_server(
    config: McpServerConfig,
    *,
    environ: Mapping[str, str] | None = None,
    factory: Any = None,
) -> McpProbeResult:
    """Connect, list tools and disconnect. A probe registers nothing."""
    env = environ if environ is not None else dict(os.environ)
    bearer: str | None = None
    if config.auth_env:
        bearer = env.get(config.auth_env) or None
        if bearer is None:
            return McpProbeResult(
                name=config.name,
                connected=False,
                detail=f"{config.auth_env} is not set; the server was not contacted",
            )
    make = factory or HttpMcpConnection
    connection = None
    try:
        connection = make(config, bearer)
        await asyncio.wait_for(connection.open(), timeout=config.timeout_seconds)
        discovered = await asyncio.wait_for(connection.list_tools(), timeout=config.timeout_seconds)
    except Exception as exc:
        return McpProbeResult(
            name=config.name,
            connected=False,
            detail=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.close()
    offered = {name for name, _ in discovered}
    return McpProbeResult(
        name=config.name,
        connected=True,
        detail="connected",
        tools=sorted(set(config.tools) & offered),
    )


class McpConfigService:
    """The merged view the manager builds from, plus the save/delete rules."""

    def __init__(
        self,
        store: McpConfigStore,
        env_configs: list[McpServerConfig],
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._store = store
        self._env = {config.name: config for config in env_configs}
        self._environ = environ if environ is not None else dict(os.environ)

    def merged(self) -> list[McpServerConfig]:
        merged = dict(self._env)
        for definition in self._store.list_all():
            merged[definition.config.name] = definition.config
        return sorted(merged.values(), key=lambda item: item.name)

    def find(self, name: str) -> McpServerConfig | None:
        return next((item for item in self.merged() if item.name == name), None)

    def source(self, name: str) -> str:
        return ENV_SOURCE if name in self._env else DASHBOARD_SOURCE

    def is_environment(self, name: str) -> bool:
        return name in self._env

    def save(self, config: McpServerConfig, *, actor: ActorRef) -> McpServerDefinition:
        if config.name in self._env:
            raise McpConfigError(
                f"{config.name} is configured in HRAGENTS_MCP_SERVERS; "
                "change it in the environment instead"
            )
        definition = McpServerDefinition(
            config=config,
            updated_by=actor.actor_id,
            updated_at=utc_now(),
        )
        self._store.upsert(definition)
        return definition

    def delete(self, name: str) -> None:
        if name in self._env:
            raise McpConfigError(
                f"{name} is configured in HRAGENTS_MCP_SERVERS and cannot be deleted here"
            )
        if not self._store.delete(name):
            raise KeyError(name)

    async def probe(self, name: str) -> McpProbeResult:
        config = self.find(name)
        if config is None:
            raise KeyError(name)
        return await probe_mcp_server(config, environ=self._environ)


async def rebuild_mcp(
    agents: Any,
    old: McpManager | None,
    configs: list[McpServerConfig],
    *,
    environ: Mapping[str, str] | None = None,
) -> McpManager | None:
    """Replace the manager. Old tools are removed before names are re-registered."""
    if agents is not None and old is not None:
        agents.tools.unregister(old.registered_names)
    new: McpManager | None = None
    if agents is not None and configs:
        new = McpManager(configs, environ=dict(environ or os.environ))
        await new.connect()
        new.register(agents.tools)
    if old is not None:
        await old.close()
    return new
