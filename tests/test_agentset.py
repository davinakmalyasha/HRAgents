"""The production agent set carries the destructive-tool gate when given approvals."""

from __future__ import annotations

from hr_agents.agents.runtime import AgentRuntime
from hr_agents.agentset import build_agent_set
from hr_agents.services.approvals import ApprovalEngine
from hr_agents.services.audit import AuditChain
from hr_agents.services.people_store import ApprovalStore


async def test_building_with_approvals_wires_the_gate() -> None:
    engine = ApprovalEngine(ApprovalStore(), audit=AuditChain())
    agent_set = await build_agent_set(
        audit=AuditChain(), runtime=AgentRuntime.offline(), approvals=engine
    )

    assert agent_set.tools.approval_gate is not None


async def test_building_without_approvals_leaves_refusal_without_a_path() -> None:
    agent_set = await build_agent_set(audit=AuditChain(), runtime=AgentRuntime.offline())

    assert agent_set.tools.approval_gate is None
