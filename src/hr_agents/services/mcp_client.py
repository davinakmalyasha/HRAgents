"""External MCP servers over HTTP/SSE, with least-privilege registration.

Only HTTP/SSE is supported. A stdio server would mean spawning a process, and
this product's hard rule is that agents never get a shell; refusing the transport
is how that rule is kept rather than merely documented.

Exposure is explicit in both directions:

* the operator lists the remote tools they want, and classifies each as read,
  write or destructive — an unlisted tool is never registered, so a server
  cannot widen its own reach;
* the operator lists the agents allowed to call them; an empty list means the
  server is connected for discovery but nothing is exposed.

A connection failure degrades that server only. The app starts, the other tools
work, and the ops endpoint says which server is not answering.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
from collections.abc import Callable
from typing import Any, Protocol

from hr_agents.logging import get_logger
from hr_agents.models import McpServerConfig, McpServerStatus
from hr_agents.tools.registry import ToolDefinition, ToolImpact, ToolRegistry

logger = get_logger(__name__)

IMPACTS = {
    "read": ToolImpact.READ,
    "write": ToolImpact.WRITE,
    "destructive": ToolImpact.DESTRUCTIVE,
}

_NAME_CLEANER = re.compile(r"[^a-z0-9_.-]+")


class McpError(RuntimeError):
    """The remote server failed, or a tool reported an error."""


class McpConnection(Protocol):
    """The narrow contract the manager needs; the real client implements it."""

    async def open(self) -> None: ...

    async def list_tools(self) -> list[tuple[str, str]]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> Any: ...

    async def close(self) -> None: ...


ConnectionFactory = Callable[[McpServerConfig, str | None], McpConnection]


class HttpMcpConnection:
    """A persistent MCP client session over the streamable HTTP transport."""

    def __init__(self, config: McpServerConfig, bearer: str | None) -> None:
        self._config = config
        self._bearer = bearer
        self._http: Any = None
        self._transport: Any = None
        self._session_cm: Any = None
        self._session: Any = None

    async def open(self) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import (
            create_mcp_http_client,
            streamable_http_client,
        )

        headers = {"Authorization": f"Bearer {self._bearer}"} if self._bearer else {}
        self._http = create_mcp_http_client(headers=headers)
        self._transport = streamable_http_client(self._config.url, http_client=self._http)
        read, write, _ = await self._transport.__aenter__()
        self._session_cm = ClientSession(
            read, write, read_timeout_seconds=self._config.timeout_seconds
        )
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()

    async def list_tools(self) -> list[tuple[str, str]]:
        if self._session is None:
            raise McpError("connection is not open")
        result = await self._session.list_tools()
        return [(tool.name, tool.description or "") for tool in result.tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise McpError("connection is not open")
        return await self._session.call_tool(
            name, arguments, read_timeout_seconds=self._config.timeout_seconds
        )

    async def close(self) -> None:
        for closer in (self._session_cm, self._transport):
            if closer is None:
                continue
            try:
                await closer.__aexit__(None, None, None)
            except Exception:  # shutdown must not raise
                logger.warning("mcp.close_failed", server=self._config.name)
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                logger.warning("mcp.http_close_failed", server=self._config.name)
        self._session = None


def namespaced(server: str, tool: str) -> str:
    """`mcp.<server>.<tool>`, with tool characters safe for a registry name."""
    cleaned = _NAME_CLEANER.sub("_", tool.strip().lower()).strip("._-")
    if not cleaned:
        raise McpError(f"remote tool {tool!r} has no usable name")
    return f"mcp.{server}.{cleaned}"


def serialise_result(result: Any) -> dict[str, Any]:
    """Turn an MCP CallToolResult into a JSON-safe payload for the agent.

    Structured content wins when the server returns it; otherwise the text
    blocks are joined. A tool-level error becomes an exception so the registry
    records the call as failed rather than as a successful result with a
    misleading body.
    """
    is_error = bool(getattr(result, "isError", False))
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        payload: dict[str, Any] = {"structured": structured}
    else:
        parts: list[Any] = []
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
            elif hasattr(block, "model_dump"):
                parts.append(block.model_dump(mode="json"))
            else:
                parts.append(str(block))
        payload = {"content": parts}
    if is_error:
        detail = payload.get("content") or payload.get("structured")
        raise McpError(f"remote tool reported an error: {str(detail)[:500]}")
    return payload


class McpManager:
    """Connects, registers and closes the configured MCP servers."""

    def __init__(
        self,
        configs: list[McpServerConfig],
        *,
        factory: ConnectionFactory | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._configs = list(configs)
        self._factory = factory or (lambda config, bearer: HttpMcpConnection(config, bearer))
        self._environ = environ if environ is not None else dict(os.environ)
        self._connections: dict[str, McpConnection] = {}
        self._available: dict[str, dict[str, str]] = {}
        self._statuses: dict[str, McpServerStatus] = {}

    async def connect(self) -> list[McpServerStatus]:
        """Open every server, best-effort. One failure never blocks the rest."""
        for config in self._configs:
            bearer: str | None = None
            if config.auth_env:
                bearer = self._environ.get(config.auth_env) or None
                if bearer is None:
                    self._fail(
                        config,
                        f"{config.auth_env} is not set; the server was not contacted",
                    )
                    continue
            connection: McpConnection | None = None
            try:
                connection = self._factory(config, bearer)
                await asyncio.wait_for(
                    self._open_and_discover(connection, config.name),
                    timeout=config.timeout_seconds,
                )
            except Exception as exc:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close()
                self._fail(config, f"{type(exc).__name__}: {exc}")
                continue
            self._connections[config.name] = connection
            discovered = self._available.get(config.name, {})
            self._statuses[config.name] = McpServerStatus(
                name=config.name,
                url=config.url,
                connected=True,
                detail="connected",
                tools=sorted(set(config.tools) & set(discovered)),
                tool_count=len(set(config.tools) & set(discovered)),
            )
            logger.info(
                "mcp.connected",
                server=config.name,
                tools=len(self._available.get(config.name, {})),
            )
        return self.statuses()

    async def _open_and_discover(self, connection: McpConnection, name: str) -> None:
        await connection.open()
        discovered = await connection.list_tools()
        self._available[name] = {tool: description for tool, description in discovered}

    def register(self, registry: ToolRegistry) -> list[str]:
        """Register the exposed tools; return the names added.

        Destructive remote tools are left out: the registry requires a dry-run
        preview for them, and an MCP tool has no way to produce one without
        making the call. An empty agent list registers nothing — the server is
        connected for discovery, not exposure.
        """
        added: list[str] = []
        for config in self._configs:
            connection = self._connections.get(config.name)
            discovered = self._available.get(config.name)
            if connection is None or discovered is None:
                continue
            available = sorted(set(config.tools) & set(discovered))
            missing = sorted(set(config.tools) - set(discovered))
            destructive = [
                remote
                for remote in available
                if IMPACTS[config.tools[remote]] is ToolImpact.DESTRUCTIVE
            ]
            exposed = [remote for remote in available if remote not in destructive]
            notes: list[str] = []
            if missing:
                notes.append(f"not offered by the server: {', '.join(missing)}")
            if destructive:
                notes.append(
                    "destructive tools not registered (no preview contract): "
                    + ", ".join(destructive)
                )
            if not config.allowed_agents:
                notes.append("no agents allowed; discovery only")
            current = self._statuses.get(config.name)
            if current is not None:
                self._statuses[config.name] = current.model_copy(
                    update={
                        "tools": exposed,
                        "tool_count": len(exposed),
                        "detail": "; ".join(notes) if notes else "connected",
                    }
                )
            if not config.allowed_agents:
                continue
            for remote in exposed:
                name = namespaced(config.name, remote)
                impact = IMPACTS[config.tools[remote]]
                registry.register(
                    ToolDefinition(
                        name=name,
                        description=discovered[remote] or f"{remote} on {config.name}",
                        allowed_agents=frozenset(agent.lower() for agent in config.allowed_agents),
                        handler=self._handler(connection, remote),
                        tags=frozenset({"mcp", config.name}),
                        impact=impact,
                    )
                )
                added.append(name)
        return added

    def _handler(self, connection: McpConnection, remote: str) -> Callable[..., Any]:
        async def call(**arguments: Any) -> dict[str, Any]:
            return serialise_result(await connection.call(remote, arguments))

        call.__name__ = f"mcp_{remote}"
        return call

    def statuses(self) -> list[McpServerStatus]:
        return [
            self._statuses[config.name] for config in self._configs if config.name in self._statuses
        ]

    async def close(self) -> None:
        for connection in self._connections.values():
            try:
                await connection.close()
            except Exception:
                logger.warning("mcp.close_failed")
        self._connections.clear()

    def _fail(self, config: McpServerConfig, detail: str) -> None:
        self._statuses[config.name] = McpServerStatus(
            name=config.name,
            url=config.url,
            connected=False,
            detail=detail,
            tools=[],
            tool_count=0,
        )
        logger.warning("mcp.unavailable", server=config.name, detail=detail)
