"""Role-carrying principals for tests that cross an authorization boundary.

`ApprovalEngine.decide` requires the actor to hold the authority the approval is
assigned to. That is the correct rule -- `RoleId.FANAGER` and `RoleId.FINANCE`
both hold `APPROVALS_DECIDE`, so without the check either could sign off the
other's work -- but it means a test actor has to say who it is.

`ActorRef.legacy("Budi")` cannot: it is a bare string with no provenance and no
role, which is exactly the shape the check refuses. Writing
`ActorRef(ActorType.HUMAN, ActorProvenance.AUTHENTICATED, role=...)` at every
call site would bury the tests in constructor noise and make the role easy to
get wrong silently, so the constructors live here and the call sites name the
authority instead.

These are the shapes `APPROVER_ROLE_HOLDERS` defines. `data_protection` maps to
`HR_ADMIN` alone at this deployment -- there is no data-protection-officer role
yet, and `rbac.py` says so rather than inventing one.
"""

from __future__ import annotations

from hr_agents.identity import ActorProvenance, ActorRef, ActorType
from hr_agents.models import ApproverRole
from hr_agents.rbac import RoleId


def principal(role: RoleId, actor_id: str) -> ActorRef:
    """An authenticated human holding exactly ``role``."""
    return ActorRef(
        actor_id=actor_id,
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=role.value,
    )


def approver(approver_role: ApproverRole | str, actor_id: str) -> ActorRef:
    """The weakest principal that may decide an approval assigned to this role.

    Derived from the table rather than hardcoded, so a change to
    `APPROVER_ROLE_HOLDERS` moves these helpers with it.
    """
    from hr_agents.rbac import approver_holders

    holders = approver_holders(str(approver_role))
    assert holders, f"no principal role can satisfy {approver_role}"
    return principal(min(holders, key=lambda item: list(RoleId).index(item)), actor_id)


def manager(actor_id: str = "Budi") -> ActorRef:
    return principal(RoleId.MANAGER, actor_id)


def finance(actor_id: str = "finance-lead") -> ActorRef:
    return principal(RoleId.FINANCE, actor_id)


def recruiter(actor_id: str = "Sinta") -> ActorRef:
    return principal(RoleId.RECRUITER, actor_id)


def hr_admin(actor_id: str = "Rina") -> ActorRef:
    return principal(RoleId.HR_ADMIN, actor_id)


def data_protection(actor_id: str = "dpo-nadia") -> ActorRef:
    """`data_protection` resolves to `HR_ADMIN` alone in this deployment."""
    return approver(ApproverRole.DATA_PROTECTION, actor_id)
