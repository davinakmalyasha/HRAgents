"""Register growth tables with the metadata so Alembic sees them."""

from hr_agents.db.growth_tables import (
    GoalRecord,
    ReviewAssignmentRecord,
    ReviewCycleRecord,
    ReviewSummaryRecord,
)

__all__ = [
    "GoalRecord",
    "ReviewAssignmentRecord",
    "ReviewCycleRecord",
    "ReviewSummaryRecord",
]
