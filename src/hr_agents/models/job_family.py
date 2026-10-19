"""The occupation families a role can belong to.

Lives in its own module because both the job specification and the evaluation
provenance snapshot name a family; keeping the enum beside `JobSpecification`
made that second dependency a cycle.
"""

from __future__ import annotations

from enum import StrEnum


class JobFamily(StrEnum):
    """The occupation a role belongs to, which selects the scoring rubric.

    This is a property of the *role*, not of the workspace. `WorkspaceId` decides which
    agents and tools a department sees; `JobFamily` decides what counts as evidence of
    competence. They are different things and are named differently on purpose.

    `ENGINEERING` is the default so every job created before this field existed is scored
    by exactly the rubric it was always scored by. The calibration corpus pins that.
    """

    ENGINEERING = "engineering"
    FINANCE = "finance"
    EDUCATION = "education"
    HEALTHCARE = "healthcare"
    LEGAL = "legal"
    OPERATIONS = "operations"
    SALES = "sales"
    GENERAL = "general"
