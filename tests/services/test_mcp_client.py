"""MCP over HTTP: explicit exposure, impacts, degradation, redaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from hr_agents.models import McpServerConfig
from hr_agents.services.mcp_client import (
    McpError,
    McpManager,
    namespaced,
    serialise_result,
)
from hr_agents.tools.registry import ToolPermissionError, ToolRegistry

TOOLS = [
    ("get_issue", "Read one issue"),
    ("create_issue", "Create an issue"),
    ("delete_issue", "Delete an issue"),
]


@dataclass
class FakeResult:
    content: list[Any] = field(default_factory=list)
    isError: bool = False
    structuredContent: Any = None


class FakeConnection:
    def __init__(self, *, fail: Exception | None = None, result: FakeResult | None = None) -> None:
        self.fail = fail
        self.result = result or FakeResult(content=[SimpleNamespace(text="ok")])
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    async def open(self) -> None:
        if self.fail is not None:
            raise self.fail

    async def list_tools(self) -> list[tuple[str, str]]:
        return TOOLS

    async def call(self, name: str, arguments: dict[str, Any]) -> FakeResult:
        self.calls.append((name, arguments))
        return self.result

    async def close(self) -> None:
        self.closed = True


def server(**overrides: Any) -> McpServerConfig:
    data: dict[str, Any] = {
        "name": "gh",
        "url": "https://mcp.example.com/mcp",
        "allowed_agents": ["screening_coordinator"],
        "tools": {"get_issue": "read", "create_issue": "write"},
    }
    data.update(overrides)
    return McpServerConfig(**data)


def manager(
    configs: list[McpServerConfig],
    connections: dict[str, FakeConnection],
    *,
    environ: dict[str, str] | None = None,
) -> McpManager:
    return McpManager(
        configs,
        factory=lambda config, bearer: connections[config.name],
        environ=environ or {},
    )


async def connected(
    config: McpServerConfig | None = None,
    connection: FakeConnection | None = None,
) -> tuple[McpManager, FakeConnection, ToolRegistry]:
    config = config or server()
    connection = connection or FakeConnection()
    mcp = manager([config], {config.name: connection})
    await mcp.connect()
    registry = ToolRegistry()
    mcp.register(registry)
    return mcp, connection, registry


async def test_only_the_configured_tools_are_registered_with_their_impacts() -> None:
    mcp, _, registry = await connected()

    names = set(registry.names())
    assert names == {"mcp.gh.get_issue", "mcp.gh.create_issue"}
    assert "mcp.gh.delete_issue" not in names
    read = registry.get("mcp.gh.get_issue")
    write = registry.get("mcp.gh.create_issue")
    assert read.impact.value == "read"
    assert read.dry_run_safe is True
    assert write.impact.value == "write"
    assert mcp.statuses()[0].tool_count == 2


async def test_an_allowed_agent_calls_the_remote_tool() -> None:
    _, connection, registry = await connected()

    result = await registry.execute(
        agent_name="screening_coordinator",
        tool_name="mcp.gh.get_issue",
        arguments={"number": 7},
    )

    assert connection.calls == [("get_issue", {"number": 7})]
    assert result == {"content": ["ok"]}


async def test_an_unlisted_agent_is_refused() -> None:
    _, connection, registry = await connected()

    with pytest.raises(ToolPermissionError):
        await registry.execute(
            agent_name="policy_assistant",
            tool_name="mcp.gh.get_issue",
            arguments={},
        )
    assert connection.calls == []


async def test_a_destructive_tool_is_not_registered_without_a_preview() -> None:
    config = server(tools={"delete_issue": "destructive"})
    mcp, connection, registry = await connected(config)

    assert "mcp.gh.delete_issue" not in registry.names()
    assert "no preview contract" in mcp.statuses()[0].detail
    assert connection.calls == []


async def test_a_catalog_derived_config_registers_with_the_template_impacts() -> None:
    from hr_agents.services.mcp_catalog import config_for
    from hr_agents.services.mcp_client import McpManager

    config = config_for("slack", "https://mcp.example.com/slack")

    class SlackConnection:
        async def open(self) -> None:
            return None

        async def list_tools(self) -> list[tuple[str, str]]:
            return [("post_message", "Post a message")]

        async def call(self, name: str, arguments: dict[str, object]) -> object:
            return {}

        async def close(self) -> None:
            return None

    mcp = McpManager(
        [config],
        factory=lambda cfg, bearer: SlackConnection(),
        environ={"SLACK_MCP_TOKEN": "test-token"},
    )
    await mcp.connect()
    registry = ToolRegistry()
    added = mcp.register(registry)

    assert added == ["mcp.slack.post_message"]
    assert registry.get("mcp.slack.post_message").impact.value == "write"
    assert mcp.statuses()[0].tool_count == 1


async def test_an_empty_agent_list_is_discovery_only() -> None:
    config = server(allowed_agents=[])
    mcp, _, registry = await connected(config)

    assert registry.names() == []
    assert "discovery only" in mcp.statuses()[0].detail


async def test_a_missing_token_variable_degrades_without_contacting_the_server() -> None:
    config = server(auth_env="GH_MCP_TOKEN")
    connection = FakeConnection()
    mcp = manager([config], {"gh": connection}, environ={})

    statuses = await mcp.connect()

    assert statuses[0].connected is False
    assert "GH_MCP_TOKEN" in statuses[0].detail
    assert connection.calls == []


async def test_the_token_is_passed_but_never_reported() -> None:
    config = server(auth_env="GH_MCP_TOKEN")
    seen: list[str | None] = []

    def factory(config: McpServerConfig, bearer: str | None) -> FakeConnection:
        seen.append(bearer)
        return FakeConnection()

    mcp = McpManager([config], factory=factory, environ={"GH_MCP_TOKEN": "top-secret"})
    await mcp.connect()

    assert seen == ["top-secret"]
    assert "top-secret" not in str(mcp.statuses())


async def test_one_failing_server_does_not_block_the_other() -> None:
    good = server(name="ats")
    bad = server(name="hris")
    mcp = manager(
        [bad, good],
        {
            "hris": FakeConnection(fail=RuntimeError("boom")),
            "ats": FakeConnection(),
        },
    )
    statuses = {item.name: item for item in await mcp.connect()}
    registry = ToolRegistry()
    added = mcp.register(registry)

    assert statuses["hris"].connected is False
    assert statuses["ats"].connected is True
    assert all(name.startswith("mcp.ats.") for name in added)


async def test_a_tool_error_is_raised_not_returned_as_success() -> None:
    connection = FakeConnection(
        result=FakeResult(content=[SimpleNamespace(text="quota exceeded")], isError=True)
    )
    _, _, registry = await connected(connection=connection)

    with pytest.raises(McpError, match="quota exceeded"):
        await registry.execute(
            agent_name="screening_coordinator",
            tool_name="mcp.gh.get_issue",
            arguments={},
        )


async def test_structured_content_is_preserved() -> None:
    connection = FakeConnection(result=FakeResult(structuredContent={"id": 1}))
    _, _, registry = await connected(connection=connection)

    result = await registry.execute(
        agent_name="screening_coordinator",
        tool_name="mcp.gh.get_issue",
        arguments={},
    )

    assert result == {"structured": {"id": 1}}


def test_tool_names_are_namespaced_and_sanitised() -> None:
    assert namespaced("gh", "Create Issue!") == "mcp.gh.create_issue"
    assert namespaced("gh", "get_issue") == "mcp.gh.get_issue"


def test_non_local_plain_http_is_refused() -> None:
    with pytest.raises(ValueError, match="plain HTTP"):
        server(url="http://mcp.example.com/mcp")
    with pytest.raises(ValueError, match="credentials"):
        server(url="https://user:pass@mcp.example.com/mcp")
    assert server(url="http://localhost:9000/mcp").url.endswith("/mcp")


def test_a_result_without_text_or_structure_is_still_serialisable() -> None:
    assert serialise_result(FakeResult(content=[])) == {"content": []}
