"""Role-based access control: roles, permissions, and principals.

Permissions are coarse-grained capability strings checked at the API boundary.
Agents are never principals: an agent acts through a request whose principal is
a named human (or an operator-owned key), so every audited action keeps a human
accountable actor.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from hr_agents.models import StrictModel


class RoleId(StrEnum):
    HR_ADMIN = "hr_admin"
    RECRUITER = "recruiter"
    FINANCE = "finance"
    MANAGER = "manager"
    EMPLOYEE = "employee"


class Permission(StrEnum):
    ADMIN_MANAGE = "admin:manage"
    RECRUITING_READ = "recruiting:read"
    RECRUITING_WRITE = "recruiting:write"
    RECRUITING_OVERRIDE = "recruiting:override"
    PEOPLE_READ = "people:read"
    PEOPLE_WRITE = "people:write"
    PAYROLL_READ = "payroll:read"
    PAYROLL_WRITE = "payroll:write"
    PAYROLL_APPROVE = "payroll:approve"
    RATES_VERIFY = "rates:verify"
    COMPLIANCE_READ = "compliance:read"
    COMPLIANCE_WRITE = "compliance:write"
    COMPLIANCE_EXECUTE = "compliance:execute"
    APPROVALS_DECIDE = "approvals:decide"
    TASKS_WRITE = "tasks:write"
    CHAT_USE = "chat:use"
    AUDIT_READ = "audit:read"


ROLE_PERMISSIONS: dict[RoleId, frozenset[Permission]] = {
    RoleId.HR_ADMIN: frozenset(Permission),
    RoleId.RECRUITER: frozenset(
        {
            Permission.RECRUITING_READ,
            Permission.RECRUITING_WRITE,
            Permission.RECRUITING_OVERRIDE,
            Permission.PEOPLE_READ,
            Permission.TASKS_WRITE,
            Permission.CHAT_USE,
        }
    ),
    RoleId.FINANCE: frozenset(
        {
            Permission.PAYROLL_READ,
            Permission.PAYROLL_WRITE,
            Permission.PAYROLL_APPROVE,
            Permission.RATES_VERIFY,
            Permission.PEOPLE_READ,
            Permission.TASKS_WRITE,
            Permission.APPROVALS_DECIDE,
            Permission.CHAT_USE,
        }
    ),
    RoleId.MANAGER: frozenset(
        {
            Permission.PEOPLE_READ,
            Permission.APPROVALS_DECIDE,
            Permission.TASKS_WRITE,
            Permission.CHAT_USE,
        }
    ),
    RoleId.EMPLOYEE: frozenset({Permission.CHAT_USE}),
}


class Principal(StrictModel):
    """The authenticated actor behind one request."""

    actor_id: str = Field(min_length=1, max_length=200)
    role: RoleId

    @property
    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[self.role]


def has_permission(principal: Principal, permission: Permission) -> bool:
    return permission in principal.permissions
