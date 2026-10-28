"""The connector catalog is content, so guard what it is allowed to say."""

from __future__ import annotations

import pytest

from hr_agents.models import McpServerConfig
from hr_agents.services.mcp_catalog import catalog, config_for, get_entry

FORBIDDEN = ("reject", "approve", "delete", "erase", "payroll", "terminate")


def test_ids_are_unique_and_cover_the_four_categories() -> None:
    entries = catalog()
    assert len({entry.id for entry in entries}) == len(entries)
    assert {entry.id for entry in entries} == {"ats", "hris", "slack", "calendar"}


def test_every_entry_carries_the_enablement_contract() -> None:
    for entry in catalog():
        assert entry.summary
        assert entry.data_flow
        assert entry.scopes
        assert entry.enable_steps
        assert entry.auth_env
        assert entry.auth_hint
        assert entry.tools
        assert entry.allowed_agents


def test_no_template_exposes_a_decision_or_a_destructive_tool() -> None:
    for entry in catalog():
        assert "destructive" not in entry.tools.values()
        for tool in entry.tools:
            assert not any(word in tool.lower() for word in FORBIDDEN), (entry.id, tool)


def test_config_for_binds_a_template_leaving_impacts_and_agents_intact() -> None:
    config = config_for("slack", "https://mcp.example.com/slack")

    assert isinstance(config, McpServerConfig)
    assert config.name == "slack"
    assert config.url == "https://mcp.example.com/slack"
    assert config.auth_env == "SLACK_MCP_TOKEN"
    assert config.tools == {"post_message": "write"}
    assert config.allowed_agents == ["screening_coordinator"]


def test_config_for_narrows_but_never_reclassifies() -> None:
    hris = config_for("hris", "https://mcp.example.com/hris")
    assert hris.tools == {"get_employee": "read", "get_leave_balances": "read"}

    narrowed = config_for(
        "hris",
        "https://mcp.example.com/hris",
        name="hris_balances",
        tools={"get_leave_balances": "read"},
    )
    assert narrowed.name == "hris_balances"
    assert narrowed.tools == {"get_leave_balances": "read"}

    with pytest.raises(ValueError, match="does not offer"):
        config_for("hris", "https://mcp.example.com/hris", tools={"erase_all": "read"})
    with pytest.raises(ValueError, match="come from the template"):
        config_for(
            "hris",
            "https://mcp.example.com/hris",
            tools={"get_employee": "write"},
        )


def test_config_for_refuses_reclassification_and_unknown_templates() -> None:
    with pytest.raises(ValueError, match="come from the template"):
        config_for("ats", "https://mcp.example.com/ats", tools={"add_note": "destructive"})
    with pytest.raises(KeyError, match="unknown connector template"):
        config_for("workday", "https://mcp.example.com/workday")
    with pytest.raises(KeyError, match="unknown connector template"):
        get_entry("workday")


def test_no_catalog_config_registers_a_destructive_tool() -> None:
    for entry in catalog():
        config = config_for(entry.id, "https://mcp.example.com/gateway")
        assert "destructive" not in config.tools.values()
