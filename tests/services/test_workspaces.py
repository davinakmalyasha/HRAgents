"""Workspace pack registry: completeness, scoping, and fingerprint stability."""

import pytest

from hr_agents.rbac import Permission
from hr_agents.workspaces import (
    DEFAULT_WORKSPACES,
    WorkspaceError,
    WorkspaceId,
    WorkspaceRegistry,
    default_registry,
)


def test_every_workspace_defined() -> None:
    registry = default_registry()
    assert {item.id for item in registry.list_all()} == set(WorkspaceId)


def test_hiring_scopes_the_recruiting_agents() -> None:
    hiring = default_registry().get(WorkspaceId.HIRING)
    assert {
        "resume_deconstructor",
        "code_portfolio_evaluator",
        "screening_coordinator",
        "feedback_writer",
    } <= hiring.agents
    assert "recruiting.evaluation" in hiring.knowledge_namespaces
    assert Permission.RECRUITING_OVERRIDE in hiring.write_permissions


def test_payroll_workspace_is_finance_scoped() -> None:
    payroll = default_registry().get(WorkspaceId.PAYROLL)
    assert Permission.PAYROLL_READ in payroll.read_permissions
    assert Permission.RECRUITING_WRITE not in payroll.write_permissions
    assert {"payroll", "gaji"} <= payroll.keywords


def test_agent_lookup() -> None:
    registry = default_registry()
    assert [item.id for item in registry.for_agent("policy_assistant")] == [WorkspaceId.POLICY]
    assert registry.for_agent("resume_deconstructor")[0].id is WorkspaceId.HIRING
    assert registry.for_agent("unknown_agent") == []


def test_unknown_workspace_rejected() -> None:
    with pytest.raises(WorkspaceError):
        default_registry().get("nope")  # type: ignore[arg-type]


def test_fingerprint_is_stable_and_sensitive() -> None:
    assert default_registry().fingerprint() == default_registry().fingerprint()
    modified = tuple(
        item.model_copy(update={"keywords": item.keywords | {"extra"}})
        if item.id is WorkspaceId.POLICY
        else item
        for item in DEFAULT_WORKSPACES
    )
    assert WorkspaceRegistry(modified).fingerprint() != default_registry().fingerprint()
