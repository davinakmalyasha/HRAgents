"""Dashboard MCP configuration: merging, locking, probing, removal."""

from __future__ import annotations

import pytest

from hr_agents.identity import ActorProvenance, ActorRef, ActorType
from hr_agents.models import McpServerConfig
from hr_agents.services.mcp_config import (
    McpConfigError,
    McpConfigService,
    McpConfigStore,
    probe_mcp_server,
)
from hr_agents.tools.registry import ToolDefinition, ToolRegistry


def config(name: str = "ats", **overrides: object) -> McpServerConfig:
    values: dict[str, object] = {
        "name": name,
        "url": f"https://{name}.example.com/mcp",
        "tools": {"get_candidate": "read"},
        "allowed_agents": ["screening_coordinator"],
    }
    values.update(overrides)
    return McpServerConfig(**values)  # type: ignore[arg-type]


def actor() -> ActorRef:
    return ActorRef(
        actor_id="rina", actor_type=ActorType.HUMAN, provenance=ActorProvenance.AUTHENTICATED
    )


def test_dashboard_rows_add_to_the_environment_and_env_names_are_locked() -> None:
    store = McpConfigStore()
    service = McpConfigService(store, [config("hris")])
    service.save(config("ats"), actor=actor())

    assert [item.name for item in service.merged()] == ["ats", "hris"]
    assert service.source("ats") == "dashboard"
    assert service.source("hris") == "environment"

    with pytest.raises(McpConfigError, match="HRAGENTS_MCP_SERVERS"):
        service.save(config("hris"), actor=actor())
    with pytest.raises(McpConfigError, match="cannot be deleted"):
        service.delete("hris")


def test_delete_removes_only_dashboard_rows() -> None:
    service = McpConfigService(McpConfigStore(), [])
    service.save(config("ats"), actor=actor())

    service.delete("ats")
    assert service.merged() == []
    with pytest.raises(KeyError):
        service.delete("ghost")


def test_save_records_the_editor() -> None:
    store = McpConfigStore()
    service = McpConfigService(store, [])
    definition = service.save(config(), actor=actor())
    assert definition.updated_by == "rina"
    assert store.list_all()[0].config.name == "ats"


class FakeConnection:
    def __init__(self, tools: list[tuple[str, str]], *, fail: bool = False) -> None:
        self._tools = tools
        self._fail = fail
        self.closed = False

    async def open(self) -> None:
        if self._fail:
            raise RuntimeError("boom")

    async def list_tools(self) -> list[tuple[str, str]]:
        return self._tools

    async def close(self) -> None:
        self.closed = True

    async def call(self, name: str, arguments: dict[str, object]) -> object:
        return {}


async def test_probe_reports_only_configured_tools_and_disconnects() -> None:
    connection = FakeConnection([("get_candidate", "read"), ("delete_everything", "x")])
    result = await probe_mcp_server(
        config(tools={"get_candidate": "read"}), factory=lambda cfg, bearer: connection
    )
    assert result.connected is True
    assert result.tools == ["get_candidate"]
    assert connection.closed is True


async def test_probe_reports_a_failure_without_raising() -> None:
    connection = FakeConnection([], fail=True)
    result = await probe_mcp_server(config(), factory=lambda cfg, bearer: connection)
    assert result.connected is False
    assert "boom" in result.detail
    assert connection.closed is True


async def test_probe_does_not_contact_a_server_without_its_token() -> None:
    calls: list[str] = []

    def factory(cfg: McpServerConfig, bearer: str | None) -> FakeConnection:
        calls.append("called")
        return FakeConnection([])

    result = await probe_mcp_server(config(auth_env="ATS_MCP_TOKEN"), environ={}, factory=factory)
    assert result.connected is False
    assert "ATS_MCP_TOKEN" in result.detail
    assert calls == []


def test_unregister_removes_a_tool_from_the_shared_registry() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="mcp.ats.get_candidate",
            description="read",
            allowed_agents=frozenset({"screening_coordinator"}),
            handler=lambda **_: {},
        )
    )
    assert registry.names() == ["mcp.ats.get_candidate"]
    assert registry.unregister(["mcp.ats.get_candidate"]) == 1
    assert registry.names() == []


def test_unregister_is_a_no_op_for_unknown_names() -> None:
    assert ToolRegistry().unregister(["never.registered"]) == 0
