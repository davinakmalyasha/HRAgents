"""Role-based access control: roles, permissions, and principals.

Permissions are coarse-grained capability strings checked at the API boundary.
Agents are never principals: an agent acts through a request whose principal is
a named human (or an operator-owned key), so every audited action keeps a human
accountable actor.
"""

from __future__ import annotations

from collections.abc import Iterable
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
            # Recruiting a person means entering them: onboarding plans, review
            # cycles, the employee record. Those routes were guarded by
            # `people:read`, so this restores exactly the reach the recruiter
            # role had before the write permissions were named on them -- and
            # `people:read` is now genuinely a read permission.
            Permission.PEOPLE_WRITE,
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
    api_key: bool = Field(
        default=False,
        description="True when the principal came from an unbound key rather than a "
        "configured, role-bound one. A self-host install with no principals "
        "configured authenticates as a single local operator, and the audit "
        "trail should say that rather than imply a managed identity.",
    )

    @property
    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[self.role]


def has_permission(principal: Principal, permission: Permission) -> bool:
    return permission in principal.permissions


# --- approver roles -----------------------------------------------------------
#
# Two different questions, deliberately not one enum:
#
#   RoleId        "what may this principal do"          (authorization)
#   ApproverRole  "whose judgement does this need"       (workflow routing)
#
# A recruiter may be the right signer for a candidate rejection without being
# allowed to export payroll. Collapsing them would be the design error.
#
# What this table adds is the *relation* between the two vocabularies, declared
# in one place, because they did not previously reconcile: three approver roles
# (engineering_lead, recruiter_lead, data_protection) had no corresponding
# RoleId, so no configured principal could hold them. Enforcing assignee_role
# without this table would have made erasure approvals and engineering-lead
# sign-offs undecidable except by an admin — in the two most sensitive
# workflows the product has. `validate_approver_coverage` turns that class of
# mistake into a startup error instead of a stuck queue.
#
# HR_ADMIN appears in every set deliberately. For the target persona — one person
# doing all of HR — that person *is* the authority, and requiring them to hold
# six roles is impossible with a single key. Binding therefore constrains every
# deployment with two or more principals, which is exactly when it matters.
#
# DATA_PROTECTION maps to HR_ADMIN alone because the product has no
# data-protection-officer concept. Mapping it to a manager would put a fiction in
# the security record; mapping it honestly to the admin, and saying so, is the
# accurate answer until the role exists.

APPROVER_ROLE_HOLDERS: dict[str, frozenset[RoleId]] = {
    "hr_admin": frozenset({RoleId.HR_ADMIN}),
    "finance": frozenset({RoleId.FINANCE, RoleId.HR_ADMIN}),
    "manager": frozenset({RoleId.MANAGER, RoleId.HR_ADMIN}),
    "recruiter_lead": frozenset({RoleId.RECRUITER, RoleId.MANAGER, RoleId.HR_ADMIN}),
    # At an SME the hiring manager is the engineering lead.
    "engineering_lead": frozenset({RoleId.MANAGER, RoleId.HR_ADMIN}),
    "data_protection": frozenset({RoleId.HR_ADMIN}),
}


def approver_holders(approver_role: str) -> frozenset[RoleId]:
    """Principal roles that may decide an approval assigned to ``approver_role``."""
    return APPROVER_ROLE_HOLDERS.get(approver_role, frozenset())


def may_decide_for(principal: Principal, approver_role: str) -> bool:
    """Whether this principal holds the authority an approval is assigned to."""
    return principal.role in approver_holders(approver_role)


def validate_approver_coverage(approver_roles: Iterable[object]) -> None:
    """Fail fast when an approver role can never be satisfied.

    Called at startup with every ``ApproverRole`` in the domain. An undecidable
    approval is the failure mode this prevents: without the check, a new approver
    role would simply be unroutable, discovered days later as a stuck queue.
    """
    uncovered = sorted(str(role) for role in approver_roles if not approver_holders(str(role)))
    if uncovered:
        raise RoleConfigurationError(
            "no principal role can satisfy approver role(s): "
            + ", ".join(uncovered)
            + ". Add them to APPROVER_ROLE_HOLDERS, or those approvals will never "
            "be decidable."
        )


class RoleConfigurationError(RuntimeError):
    """The configured roles cannot satisfy the domain's approver requirements."""
