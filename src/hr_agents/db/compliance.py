"""Register compliance tables with the metadata so Alembic sees them."""

from hr_agents.db.compliance_tables import (
    BreachIncidentTable,
    ConsentRecordTable,
    ErasureRequestTable,
    RetentionPolicyTable,
    RetentionRecordTable,
)

__all__ = [
    "BreachIncidentTable",
    "ConsentRecordTable",
    "ErasureRequestTable",
    "RetentionPolicyTable",
    "RetentionRecordTable",
]
