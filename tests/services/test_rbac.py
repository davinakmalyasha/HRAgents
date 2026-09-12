"""RBAC role/permission matrix and principal resolution."""

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from hr_agents.api.deps import resolve_principal
from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    Principal,
    RoleId,
    has_permission,
)


def make_settings(
    *,
    api_keys: list[str] | None = None,
    api_principals: list[ApiPrincipalSettings] | None = None,
) -> Settings:
    return Settings.model_construct(
        api_keys=api_keys or [],
        api_principals=api_principals or [],
    )


def test_hr_admin_has_every_permission() -> None:
    principal = Principal(actor_id="admin", role=RoleId.HR_ADMIN)
    for permission in Permission:
        assert has_permission(principal, permission)


def test_employee_can_only_chat() -> None:
    assert ROLE_PERMISSIONS[RoleId.EMPLOYEE] == frozenset({Permission.CHAT_USE})


def test_recruiter_can_override_but_not_payroll() -> None:
    recruiter = Principal(actor_id="rec", role=RoleId.RECRUITER)
    assert has_permission(recruiter, Permission.RECRUITING_OVERRIDE)
    assert not has_permission(recruiter, Permission.PAYROLL_APPROVE)
    assert not has_permission(recruiter, Permission.COMPLIANCE_EXECUTE)


def test_finance_can_approve_payroll_but_not_recruit() -> None:
    finance = Principal(actor_id="fin", role=RoleId.FINANCE)
    assert has_permission(finance, Permission.PAYROLL_APPROVE)
    assert has_permission(finance, Permission.RATES_VERIFY)
    assert not has_permission(finance, Permission.RECRUITING_WRITE)


def test_manager_can_decide_approvals_but_not_see_payroll() -> None:
    manager = Principal(actor_id="mgr", role=RoleId.MANAGER)
    assert has_permission(manager, Permission.APPROVALS_DECIDE)
    assert not has_permission(manager, Permission.PAYROLL_READ)


def test_auth_disabled_returns_local_admin() -> None:
    principal = resolve_principal(None, make_settings())
    assert principal.role is RoleId.HR_ADMIN
    assert principal.actor_id == "local-dev"


def test_plain_keys_are_admin() -> None:
    settings = make_settings(api_keys=["secret-1"])
    assert resolve_principal("secret-1", settings).role is RoleId.HR_ADMIN
    with pytest.raises(HTTPException) as excinfo:
        resolve_principal("nope", settings)
    assert excinfo.value.status_code == 401
    with pytest.raises(HTTPException):
        resolve_principal(None, settings)


def test_role_bound_principals() -> None:
    settings = make_settings(
        api_principals=[
            ApiPrincipalSettings(
                key=SecretStr("fin-key"),
                role=RoleId.FINANCE,
                actor_id="finance-1",
            )
        ],
    )
    principal = resolve_principal("fin-key", settings)
    assert principal.actor_id == "finance-1"
    assert principal.role is RoleId.FINANCE
    with pytest.raises(HTTPException):
        resolve_principal("plain", settings)


def test_plain_keys_ignored_when_principals_configured() -> None:
    settings = make_settings(
        api_keys=["plain"],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("bound"), role=RoleId.MANAGER),
        ],
    )
    with pytest.raises(HTTPException):
        resolve_principal("plain", settings)
    assert resolve_principal("bound", settings).role is RoleId.MANAGER
