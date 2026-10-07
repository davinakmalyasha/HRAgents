"""Schemas for the caller's own session."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from hr_agents.models import StrictModel
from hr_agents.rbac import RoleId


class SessionView(StrictModel):
    """Who the server believes is making this request.

    `role` is the authoritative one for this request: it is what every permission check
    and every `assignee_role` comparison uses. A UI that guessed it from anything else
    would eventually offer a decision the server refuses.

    `decides_approver_roles` is the server's own answer, taken from
    `APPROVER_ROLE_HOLDERS`, rather than something the client works out. That table is
    many-to-many -- `hr_admin` may decide `manager`-assigned work, `finance`-assigned
    work and `data_protection`-assigned work -- and a client that copied it would be
    one table edit away from hiding every decision, or offering one it has no authority
    for. Publishing it means there is only one copy to get right.
    """

    actor_id: str
    role: RoleId
    employee_id: UUID | None = None
    api_key: bool = False
    decides_approver_roles: list[str] = Field(
        default_factory=list,
        description="Approver roles this principal may decide an approval assigned to.",
    )
