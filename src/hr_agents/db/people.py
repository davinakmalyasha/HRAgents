"""Register people tables with the metadata so Alembic sees them."""

from hr_agents.db.people_tables import (
    ApprovalRecord,
    ContractRecord,
    EmployeeDocumentRecord,
    EmployeeRecord,
    OrgUnitRecord,
    RateTableRecord,
    TaskRecord,
)

__all__ = [
    "ApprovalRecord",
    "ContractRecord",
    "EmployeeDocumentRecord",
    "EmployeeRecord",
    "OrgUnitRecord",
    "RateTableRecord",
    "TaskRecord",
]
