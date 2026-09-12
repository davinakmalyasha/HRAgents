"""API models for workspace packs (dashboard navigation metadata)."""

from __future__ import annotations

from hr_agents.models import StrictModel
from hr_agents.workspaces import WorkspaceDefinition, WorkspaceId


class WorkspaceView(StrictModel):
    """One department pack as the dashboard needs it: identity + bilingual copy."""

    id: WorkspaceId
    name_en: str
    name_id: str
    summary_en: str
    summary_id: str

    @classmethod
    def from_model(cls, definition: WorkspaceDefinition) -> WorkspaceView:
        return cls(
            id=definition.id,
            name_en=definition.name_en,
            name_id=definition.name_id,
            summary_en=definition.summary_en,
            summary_id=definition.summary_id,
        )
