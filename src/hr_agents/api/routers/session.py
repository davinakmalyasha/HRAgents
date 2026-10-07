"""The caller's own identity — who the server thinks you are.

Exists because several surfaces need the authenticated actor's role to render honestly:
the approvals inbox must hide a decision that is not the viewer's to make, and the growth
queue must show the viewer's own forms. Both were guessing before this existed, which is
how a UI ends up offering a button the server refuses.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from hr_agents.api.auth import current_principal
from hr_agents.api.session_schemas import SessionView
from hr_agents.identity import Principal
from hr_agents.models import ApproverRole
from hr_agents.rbac import RoleId, approver_holders

router = APIRouter(prefix="/v1/session", tags=["session"])


def get_principal(request: Request) -> Principal:
    """The authenticated principal.

    `current_principal` raises 401 with `auth_required` or `auth_invalid` when nothing
    usable was presented, so this endpoint can never answer "you are nobody".
    """
    return current_principal(request)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


@router.get("", response_model=SessionView, summary="Who the server thinks you are")
def read_session(principal: PrincipalDep) -> SessionView:
    """The caller's own actor id, role, employee binding and approval authority.

    Returns only what the caller already proved by authenticating. No permission is
    required beyond holding a valid credential, because there is nothing here to protect:
    it is the caller's own identity, not anyone else's.
    """
    return SessionView(
        actor_id=principal.actor_id,
        role=principal.role,
        employee_id=principal.employee_id,
        api_key=principal.api_key,
        decides_approver_roles=sorted(
            role.value
            for role in ApproverRole
            if RoleId(principal.role.value) in approver_holders(role.value)
        ),
    )
