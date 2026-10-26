"""The connector catalog is content, so guard what it is allowed to say."""

from __future__ import annotations

from hr_agents.services.mcp_catalog import catalog

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
