"""Register offboarding tables with the metadata so Alembic sees them."""

from hr_agents.db.offboarding_tables import (
    OffboardingAssetRecord,
    OffboardingPlanRecord,
    OffboardingTemplateRecord,
)

__all__ = [
    "OffboardingAssetRecord",
    "OffboardingPlanRecord",
    "OffboardingTemplateRecord",
]
