"""The dashboard MCP configuration persists as one row per name."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.mcp_servers import DbMcpConfigStore
from hr_agents.models import McpServerConfig, McpServerDefinition, utc_now


def definition(name: str = "ats") -> McpServerDefinition:
    return McpServerDefinition(
        config=McpServerConfig(
            name=name,
            url=f"https://{name}.example.com/mcp",
            tools={"get_candidate": "read"},
            allowed_agents=["screening_coordinator"],
        ),
        updated_by="rina",
        updated_at=utc_now(),
    )


def test_round_trip_and_delete(factory: sessionmaker[Session]) -> None:
    store = DbMcpConfigStore(factory)
    store.upsert(definition())

    loaded = store.list_all()
    assert [item.config.name for item in loaded] == ["ats"]
    assert loaded[0].config.tools == {"get_candidate": "read"}
    assert loaded[0].updated_by == "rina"

    store.upsert(definition())
    assert len(store.list_all()) == 1

    assert store.delete("ats") is True
    assert store.list_all() == []
    assert store.delete("ats") is False
