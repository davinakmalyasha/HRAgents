import pytest

from hr_agents.services.audit import AuditChain
from hr_agents.tools import (
    ToolDefinition,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRegistry,
)


def make_tool(name: str, agents: set[str], result: object = "ok") -> ToolDefinition:
    def handler(**kwargs: object) -> object:
        return result

    return ToolDefinition(
        name=name,
        description=f"Tool {name}",
        allowed_agents=frozenset(agents),
        handler=handler,
    )


def test_register_and_lookup() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("alpha", {"agent_a"}))

    assert "alpha" in registry
    assert registry.names() == ["alpha"]
    assert registry.get("alpha").name == "alpha"
    assert len(registry) == 1


def test_duplicate_registration_rejected() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("alpha", {"agent_a"}))
    with pytest.raises(ValueError, match="duplicate tool name"):
        registry.register(make_tool("alpha", {"agent_b"}))


def test_tool_requires_allowed_agents() -> None:
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="must declare allowed agents"):
        registry.register(make_tool("alpha", set()))


def test_unknown_tool_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError, match="unknown tool"):
        registry.get("missing")


def test_scope_visibility() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("alpha", {"agent_a"}))
    registry.register(make_tool("beta", {"agent_b"}))
    registry.register(make_tool("gamma", {"agent_a", "agent_b"}))

    assert registry.names_for("agent_a") == ["alpha", "gamma"]
    assert registry.names_for("agent_b") == ["beta", "gamma"]
    assert registry.names_for("agent_c") == []


async def test_execute_runs_handler() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("alpha", {"agent_a"}, result={"value": 42}))

    result = await registry.execute(agent_name="agent_a", tool_name="alpha")
    assert result == {"value": 42}


async def test_execute_async_handler() -> None:
    async def handler(value: int) -> int:
        return value * 2

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="doubler",
            description="Doubles",
            allowed_agents=frozenset({"agent_a"}),
            handler=handler,
        )
    )
    assert (
        await registry.execute(agent_name="agent_a", tool_name="doubler", arguments={"value": 21})
        == 42
    )


async def test_permission_denied() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("alpha", {"agent_a"}))
    with pytest.raises(ToolPermissionError, match="not permitted"):
        await registry.execute(agent_name="agent_b", tool_name="alpha")


async def test_handler_errors_propagate_and_are_audited() -> None:
    def failing() -> None:
        raise RuntimeError("boom")

    audit = AuditChain()
    registry = ToolRegistry(audit=audit)
    registry.register(
        ToolDefinition(
            name="failing",
            description="Fails",
            allowed_agents=frozenset({"agent_a"}),
            handler=failing,
        )
    )

    with pytest.raises(RuntimeError, match="boom"):
        await registry.execute(agent_name="agent_a", tool_name="failing")

    assert audit.entries[-1].payload["outcome"] == "error"
    assert audit.verify() == -1


async def test_calls_are_audited_with_hashed_arguments() -> None:
    audit = AuditChain()
    registry = ToolRegistry(audit=audit)
    registry.register(make_tool("alpha", {"agent_a"}))

    await registry.execute(
        agent_name="agent_a",
        tool_name="alpha",
        arguments={"candidate_email": "budi@example.com"},
    )

    entry = audit.entries[-1]
    assert entry.action == "tool.alpha"
    assert entry.actor.actor_id == "agent_a"
    assert entry.payload["outcome"] == "ok"
    assert "candidate_email" not in entry.payload
    assert len(entry.payload["arguments_hash"]) == 64
    assert audit.verify() == -1


async def test_denied_call_is_audited() -> None:
    audit = AuditChain()
    registry = ToolRegistry(audit=audit)
    registry.register(make_tool("alpha", {"agent_a"}))

    with pytest.raises(ToolPermissionError):
        await registry.execute(agent_name="agent_b", tool_name="alpha")

    assert audit.entries[-1].payload["outcome"] == "denied"
    assert audit.entries[-1].payload["reason"] == "agent_scope"


def test_scoped_view_hides_out_of_scope_tools() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("alpha", {"agent_a"}))
    registry.register(make_tool("beta", {"agent_a"}))

    view = registry.scoped({"alpha"}, scope_id="hiring")

    assert view.names() == ["alpha"]
    assert "alpha" in view
    assert "beta" not in view
    assert len(view) == 1
    assert view.names_for("agent_a") == ["alpha"]
    with pytest.raises(ToolNotFoundError):
        view.get("beta")


def test_scoped_view_shares_late_registrations_with_parent() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("alpha", {"agent_a"}))
    registry.register(make_tool("beta", {"agent_b"}))
    view = registry.scoped({"alpha", "gamma"})

    registry.register(make_tool("gamma", {"agent_a"}))

    assert registry.names() == ["alpha", "beta", "gamma"]
    assert view.names() == ["alpha", "gamma"]


async def test_scoped_view_denies_out_of_scope_execution_and_audits() -> None:
    audit = AuditChain()
    registry = ToolRegistry(audit=audit)
    registry.register(make_tool("beta", {"agent_a"}, result="secret"))
    view = registry.scoped({"alpha"}, scope_id="payroll")

    with pytest.raises(ToolPermissionError, match="outside workspace scope"):
        await view.execute(agent_name="agent_a", tool_name="beta")

    entry = audit.entries[-1]
    assert entry.payload["outcome"] == "denied"
    assert entry.payload["reason"] == "workspace_scope"
    assert entry.payload["workspace"] == "payroll"


async def test_scoped_view_still_enforces_agent_scope() -> None:
    audit = AuditChain()
    registry = ToolRegistry(audit=audit)
    registry.register(make_tool("alpha", {"agent_a"}))
    view = registry.scoped({"alpha"}, scope_id="hiring")

    with pytest.raises(ToolPermissionError, match="not permitted"):
        await view.execute(agent_name="agent_b", tool_name="alpha")

    assert audit.entries[-1].payload["reason"] == "agent_scope"


def test_scoped_view_rejects_registration() -> None:
    registry = ToolRegistry()
    view = registry.scoped({"alpha"})
    with pytest.raises(ValueError, match="scoped view"):
        view.register(make_tool("alpha", {"agent_a"}))


def test_scoping_cannot_widen_a_scoped_view() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("alpha", {"agent_a"}))
    registry.register(make_tool("beta", {"agent_a"}))
    view = registry.scoped({"alpha"}, scope_id="hiring")

    narrower = view.scoped({"alpha", "beta"}, scope_id="payroll")

    assert narrower.names() == ["alpha"]


def test_callable_returns_bare_handler() -> None:
    registry = ToolRegistry()
    tool = make_tool("alpha", {"agent_a"})
    registry.register(tool)
    assert tool.callable()() == "ok"
