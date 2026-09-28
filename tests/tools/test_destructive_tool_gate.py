"""Destructive tool calls must never run on an agent's say-so.

Negative tests first: every way of getting a destructive tool to run without a
named human decision is closed, and the approval path itself is checked for the
three properties that make it safe (same arguments, at most once, audited).
"""

import pytest

from hr_agents.models import ApprovalStatus, ApproverRole, payload_digest
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import ApprovalStore
from hr_agents.tools import (
    DestructiveToolError,
    DestructiveToolGate,
    ToolApprovalRequired,
    ToolDefinition,
    ToolImpact,
    ToolRegistry,
)

AGENT = "agent:payroll_integrator"


def make_engine() -> ApprovalEngine:
    return ApprovalEngine(ApprovalStore(), audit=AuditChain())


def make_destructive_tool(
    *,
    calls: list[dict[str, object]] | None = None,
    dry_run: bool = True,
    supports_dry_run: bool = True,
) -> ToolDefinition:
    """A destructive tool that records only real executions, never previews."""
    recorded = calls if calls is not None else []

    def handler(dry_run: bool = False, **kwargs: object) -> dict[str, object]:
        if dry_run:
            if not supports_dry_run:
                raise TypeError("dry_run is not supported")
            return {"would_delete": kwargs.get("employee_id"), "dry_run": True}
        recorded.append(kwargs)
        return {"would_delete": kwargs.get("employee_id"), "dry_run": False}

    return ToolDefinition(
        name="mcp.hris.delete_employee",
        description="Deletes an employee record in the external HRIS",
        allowed_agents=frozenset({AGENT}),
        handler=handler,
        dry_run_safe=dry_run,
        impact=ToolImpact.DESTRUCTIVE,
        approver_role=ApproverRole.HR_ADMIN,
    )


def make_registry(
    tool: ToolDefinition, audit: AuditChain, gate: DestructiveToolGate
) -> ToolRegistry:
    registry = ToolRegistry(audit=audit)
    registry.register(tool)
    return registry.with_approval_gate(gate)


# --- the refusals -------------------------------------------------------------


async def test_agent_cannot_execute_a_destructive_tool_directly() -> None:
    calls: list[dict[str, object]] = []
    audit = AuditChain()
    gate = DestructiveToolGate(make_engine())
    registry = make_registry(make_destructive_tool(calls=calls), audit, gate)

    with pytest.raises(ToolApprovalRequired, match="destructive"):
        await registry.execute(
            agent_name=AGENT,
            tool_name="mcp.hris.delete_employee",
            arguments={"employee_id": "emp-1"},
        )

    # The handler was never touched, and the refusal is on the audit chain.
    assert calls == []
    denial = [entry for entry in audit.entries if entry.payload.get("outcome") == "denied"]
    assert len(denial) == 1
    assert denial[0].payload["reason"] == "human_approval_required"
    assert audit.verify() == -1


async def test_destructive_tool_without_a_gate_refuses_even_a_permitted_agent() -> None:
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    registry.register(make_destructive_tool(calls=calls))

    with pytest.raises(ToolApprovalRequired, match="no approval gate"):
        await registry.execute(
            agent_name=AGENT,
            tool_name="mcp.hris.delete_employee",
            arguments={"employee_id": "emp-1"},
        )
    assert calls == []


def test_destructive_tool_must_be_dry_run_safe() -> None:
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="dry-run safe"):
        registry.register(make_destructive_tool(dry_run=False))


def test_a_tool_that_cannot_be_previewed_is_not_requested() -> None:
    gate = DestructiveToolGate(make_engine())
    with pytest.raises(DestructiveToolError, match="cannot be previewed"):
        gate.request(
            make_destructive_tool(supports_dry_run=False),
            agent_name=AGENT,
            arguments={"employee_id": "emp-1"},
        )


def test_non_destructive_tool_needs_no_approval() -> None:
    gate = DestructiveToolGate(make_engine())
    read_only = ToolDefinition(
        name="mcp.hris.read_employee",
        description="Reads an employee record",
        allowed_agents=frozenset({AGENT}),
        handler=lambda **_: {"ok": True},
        impact=ToolImpact.READ,
    )
    with pytest.raises(DestructiveToolError, match="not destructive"):
        gate.request(read_only, agent_name=AGENT, arguments={})


def test_execution_without_an_approval_is_refused() -> None:
    calls: list[dict[str, object]] = []
    gate = DestructiveToolGate(make_engine())
    tool = make_destructive_tool(calls=calls)

    with pytest.raises(DestructiveToolError, match="no approval matches"):
        gate.execute_approved(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})
    assert calls == []


def test_execution_is_refused_while_the_request_is_pending() -> None:
    calls: list[dict[str, object]] = []
    gate = DestructiveToolGate(make_engine())
    tool = make_destructive_tool(calls=calls)
    gate.request(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})

    with pytest.raises(DestructiveToolError, match="is pending"):
        gate.execute_approved(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})
    assert calls == []


def test_execution_is_refused_after_a_rejection() -> None:
    calls: list[dict[str, object]] = []
    engine = make_engine()
    gate = DestructiveToolGate(engine)
    tool = make_destructive_tool(calls=calls)
    ticket = gate.request(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})
    engine.decide(ticket.request_id, decided_by="Sinta", approve=False, reason="wrong record")

    with pytest.raises(DestructiveToolError, match="is rejected"):
        gate.execute_approved(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})
    assert calls == []


def test_approved_arguments_cannot_be_swapped_after_the_human_read_them() -> None:
    calls: list[dict[str, object]] = []
    engine = make_engine()
    gate = DestructiveToolGate(engine)
    tool = make_destructive_tool(calls=calls)
    ticket = gate.request(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})
    engine.decide(ticket.request_id, decided_by="Sinta", approve=True)

    with pytest.raises(DestructiveToolError, match="different arguments"):
        gate.execute_approved(tool, agent_name=AGENT, arguments={"employee_id": "emp-2"})
    assert calls == []


def test_another_agent_cannot_spend_someone_elses_approval() -> None:
    calls: list[dict[str, object]] = []
    engine = make_engine()
    gate = DestructiveToolGate(engine)
    tool = make_destructive_tool(calls=calls)
    ticket = gate.request(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})
    engine.decide(ticket.request_id, decided_by="Sinta", approve=True)

    # The grant is bound to the requesting agent, so another agent has none.
    with pytest.raises(DestructiveToolError, match="for this agent"):
        gate.execute_approved(tool, agent_name="agent:other", arguments={"employee_id": "emp-1"})
    assert calls == []


def test_an_approval_runs_the_tool_at_most_once() -> None:
    calls: list[dict[str, object]] = []
    engine = make_engine()
    gate = DestructiveToolGate(engine)
    tool = make_destructive_tool(calls=calls)
    ticket = gate.request(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})
    engine.decide(ticket.request_id, decided_by="Sinta", approve=True)

    first = gate.execute_approved(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})
    with pytest.raises(DestructiveToolError, match="already executed once"):
        gate.execute_approved(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})

    assert calls == [{"employee_id": "emp-1"}]
    assert first == {"would_delete": "emp-1", "dry_run": False}


def test_an_agent_cannot_decide_its_own_destructive_call() -> None:
    from hr_agents.services.approvals import ApprovalError

    engine = make_engine()
    gate = DestructiveToolGate(engine)
    ticket = gate.request(
        make_destructive_tool(), agent_name=AGENT, arguments={"employee_id": "emp-1"}
    )

    with pytest.raises(ApprovalError, match="named human"):
        engine.decide(ticket.request_id, decided_by=AGENT, approve=True)


# --- the happy path, and its guarantees ---------------------------------------


def test_the_approval_carries_the_preview_the_human_approved() -> None:
    engine = make_engine()
    gate = DestructiveToolGate(engine)
    tool = make_destructive_tool()
    arguments = {"employee_id": "emp-1"}

    ticket = gate.request(tool, agent_name=AGENT, arguments=arguments)
    stored = engine.find(ticket.request_id)

    assert stored is not None
    assert stored.assignee_role is ApproverRole.HR_ADMIN
    assert stored.requested_by_agent is True
    assert stored.urgency.value == "high"
    assert stored.payload["preview"] == {"result": {"would_delete": "emp-1", "dry_run": True}}
    assert stored.payload["arguments_hash"] == payload_digest(arguments)
    assert ticket.status is ApprovalStatus.PENDING
    assert ticket.preview["result"]["dry_run"] is True


def test_asking_twice_returns_the_same_open_request() -> None:
    engine = make_engine()
    gate = DestructiveToolGate(engine)
    tool = make_destructive_tool()
    arguments = {"employee_id": "emp-1"}

    first = gate.request(tool, agent_name=AGENT, arguments=arguments)
    second = gate.request(tool, agent_name=AGENT, arguments=arguments)

    assert first.request_id == second.request_id
    assert len(engine.list_all()) == 1


def test_the_approved_execution_is_audited_with_the_approval_id() -> None:
    audit = AuditChain()
    engine = ApprovalEngine(ApprovalStore(), audit=audit)
    gate = DestructiveToolGate(engine, audit=audit)
    tool = make_destructive_tool()
    ticket = gate.request(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})
    engine.decide(ticket.request_id, decided_by="Sinta", approve=True, reason="documented")

    gate.execute_approved(tool, agent_name=AGENT, arguments={"employee_id": "emp-1"})

    actions = [entry.action for entry in audit.entries]
    assert "tool.destructive_requested" in actions
    assert "tool.destructive_executed" in actions
    assert "approval.executed" in actions
    executed = next(entry for entry in audit.entries if entry.action == "tool.destructive_executed")
    assert executed.payload["approval_id"] == str(ticket.request_id)
    # The audit trail carries the digest, never the arguments themselves.
    assert "arguments" not in executed.payload
    assert executed.payload["arguments_hash"] == payload_digest({"employee_id": "emp-1"})
    assert audit.verify() == -1


def test_narrowing_a_workspace_view_never_drops_the_human_gate() -> None:
    gate = DestructiveToolGate(make_engine())
    audit = AuditChain()
    registry = ToolRegistry(audit=audit)
    registry.register(make_destructive_tool())
    registry.register(
        ToolDefinition(
            name="read_only",
            description="Reads",
            allowed_agents=frozenset({AGENT}),
            handler=lambda **_: {"ok": True},
        )
    )
    view = registry.with_approval_gate(gate).scoped(
        {"mcp.hris.delete_employee"}, scope_id="payroll"
    )

    assert view.names() == ["mcp.hris.delete_employee"]
    assert view.approval_gate is gate
