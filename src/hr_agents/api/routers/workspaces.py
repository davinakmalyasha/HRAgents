"""Workspace metadata endpoints — the dashboard's navigation source of truth."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from hr_agents.api.deps import require_permission
from hr_agents.api.workspace_schemas import WorkspaceView
from hr_agents.rbac import Permission
from hr_agents.workspaces import default_registry

router = APIRouter(
    prefix="/v1/workspaces",
    tags=["workspaces"],
    dependencies=[Depends(require_permission(Permission.CHAT_USE))],
)


@router.get("", response_model=list[WorkspaceView], summary="Department packs for navigation")
def list_workspaces() -> list[WorkspaceView]:
    """Every workspace pack, in the deterministic enum order."""
    return [WorkspaceView.from_model(pack) for pack in default_registry().list_all()]
