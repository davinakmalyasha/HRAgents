"""RBAC role/permission matrix, principal resolution, and approver-role binding.

Negative tests come first per the repo convention: a gate is worthless until
something proves it refuses.
"""

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from hr_agents.api.auth import auth_is_configured, lookup_principal
from hr_agents.api.deps import resolve_principal
from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.models import ApproverRole
from hr_agents.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    Principal,
    RoleConfigurationError,
    RoleId,
    approver_holders,
    has_permission,
    may_decide_for,
    validate_approver_coverage,
)


def make_settings(
    *,
    api_keys: list[str] | None = None,
    api_principals: list[ApiPrincipalSettings] | None = None,
    actor_name: str = "",
) -> Settings:
    return Settings.model_construct(
        api_keys=api_keys or [],
        api_principals=api_principals or [],
        actor_name=actor_name,
    )


def test_hr_admin_has_every_permission() -> None:
    principal = Principal(actor_id="admin", role=RoleId.HR_ADMIN)
    for permission in Permission:
        assert has_permission(principal, permission)


def test_employee_chats_and_acts_on_their_own_records() -> None:
    """An employee's reach is self-service, and nothing else.

    This role used to hold ``chat:use`` alone, which meant an employee could not
    request their own leave -- the capability the whole product exists to
    provide. ``self_service`` is what they gained, and it is deliberately narrow:
    what they may act on is settled per record by ``ActorRef.may_act_for``, not by
    holding this. They still see no employee directory and touch nobody else's.
    """
    assert ROLE_PERMISSIONS[RoleId.EMPLOYEE] == frozenset(
        {Permission.CHAT_USE, Permission.SELF_SERVICE}
    )

    employee = Principal(actor_id="sari", role=RoleId.EMPLOYEE)
    assert not has_permission(employee, Permission.PEOPLE_READ)
    assert not has_permission(employee, Permission.PEOPLE_WRITE)
    assert not has_permission(employee, Permission.RECRUITING_READ)
    assert not has_permission(employee, Permission.PAYROLL_READ)


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
    assert principal.api_key is False


def test_local_operator_can_be_named() -> None:
    """An unconfigured install still writes an audit entry; 'local-dev' is not a person."""
    principal = resolve_principal(None, make_settings(actor_name="Rina"))
    assert principal.actor_id == "Rina"


def test_plain_keys_are_admin() -> None:
    settings = make_settings(api_keys=["secret-1"])
    resolved = resolve_principal("secret-1", settings)
    assert resolved.role is RoleId.HR_ADMIN
    assert resolved.api_key is True
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


# --- lookup_principal: resolves without raising, so middleware can never 500 ---


def test_lookup_returns_none_instead_of_raising() -> None:
    """A refused key must be a value here, not an exception.

    The middleware runs on every request including /healthz, so raising here
    would turn a bad key into a 500 on an unauthenticated endpoint.
    """
    assert lookup_principal("nope", make_settings(api_keys=["right"])) is None
    assert lookup_principal(None, make_settings(api_keys=["right"])) is None
    assert lookup_principal("right", make_settings(api_keys=["right"])) is not None


def test_auth_is_configured() -> None:
    assert not auth_is_configured(make_settings())
    assert auth_is_configured(make_settings(api_keys=["k"]))
    assert auth_is_configured(
        make_settings(api_principals=[ApiPrincipalSettings(key=SecretStr("k"))])
    )


# --- approver roles vs authorization roles ------------------------------------


def test_every_approver_role_is_satisfiable() -> None:
    """Startup validation: an undecidable approval is a stuck queue, not a warning."""
    validate_approver_coverage(ApproverRole)


def test_unsatisfiable_approver_role_fails_fast() -> None:
    with pytest.raises(RoleConfigurationError) as excinfo:
        validate_approver_coverage([ApproverRole.HR_ADMIN, "invented_role"])
    assert "invented_role" in str(excinfo.value)


def test_approver_role_with_no_holders_resolves_empty() -> None:
    assert approver_holders("invented_role") == frozenset()


def test_manager_cannot_decide_finance_or_privacy_approvals() -> None:
    """The negative that matters: role separation is real, not decorative."""
    manager = Principal(actor_id="mgr", role=RoleId.MANAGER)
    assert may_decide_for(manager, ApproverRole.MANAGER.value)
    assert may_decide_for(manager, ApproverRole.ENGINEERING_LEAD.value)
    assert not may_decide_for(manager, ApproverRole.FINANCE.value)
    assert not may_decide_for(manager, ApproverRole.DATA_PROTECTION.value)
    assert not may_decide_for(manager, ApproverRole.HR_ADMIN.value)


def test_finance_cannot_decide_a_hiring_approval() -> None:
    finance = Principal(actor_id="fin", role=RoleId.FINANCE)
    assert may_decide_for(finance, ApproverRole.FINANCE.value)
    assert not may_decide_for(finance, ApproverRole.RECRUITER_LEAD.value)
    assert not may_decide_for(finance, ApproverRole.ENGINEERING_LEAD.value)


def test_recruiter_lead_decided_by_recruiter_or_manager() -> None:
    assert may_decide_for(Principal(actor_id="r", role=RoleId.RECRUITER), "recruiter_lead")
    assert may_decide_for(Principal(actor_id="m", role=RoleId.MANAGER), "recruiter_lead")
    assert not may_decide_for(Principal(actor_id="f", role=RoleId.FINANCE), "recruiter_lead")


def test_hr_admin_overrides_every_approver_role() -> None:
    """Deliberate: the single-operator persona *is* the authority."""
    admin = Principal(actor_id="admin", role=RoleId.HR_ADMIN)
    for role in ApproverRole:
        assert may_decide_for(admin, role.value), role


def test_data_protection_maps_to_hr_admin_only() -> None:
    """No DPO role exists yet, and inventing one would be a fiction in the record."""
    assert approver_holders(ApproverRole.DATA_PROTECTION.value) == frozenset({RoleId.HR_ADMIN})
