"""Every tenant-scoped table must have an index on tenant_id.

Row-level security adds ``tenant_id = ...`` to every query. A table without an index on
that column makes the isolation layer a sequential scan of the whole table, so the
security mechanism sets the performance floor for the database. This schema went fourteen
migrations with no table indexed, and it was only caught by reading the code.

Enforced structurally rather than by convention, because a convention is what failed.
"""

from __future__ import annotations

from sqlalchemy import Index

from hr_agents.db import (  # noqa: F401
    compliance_tables,
    growth_tables,
    leave_tables,
    offboarding_tables,
    offers_tables,
    onboarding_tables,
    payroll_tables,
    people_tables,
    tables,
    workspace_tables,
)
from hr_agents.db.base import Base, tenant_index_name


def _tenant_tables() -> list[str]:
    return sorted(name for name, table in Base.metadata.tables.items() if "tenant_id" in table.c)


def test_there_are_tenant_tables_to_check() -> None:
    """A guard test that passes because it found no tables is worse than none."""
    assert len(_tenant_tables()) >= 40


def test_every_tenant_table_indexes_tenant_id() -> None:
    missing = [
        name
        for name in _tenant_tables()
        if not any(
            index.name == tenant_index_name(name) for index in Base.metadata.tables[name].indexes
        )
    ]
    assert missing == [], f"tenant_id is unindexed on {missing}"


def test_ensure_tenant_indexes_is_idempotent() -> None:
    """The hook runs on every mapper configuration, so a second call must add nothing.

    Without this, a second pass would raise on the duplicate index name the first pass
    created -- and `after_configured` fires more than once in a long-lived process.
    """
    from hr_agents.db.base import ensure_tenant_indexes

    assert ensure_tenant_indexes() == []


def test_the_tenant_index_is_a_single_column_leading_index() -> None:
    """It has to be usable by the planner as the leading column of the RLS predicate.

    A unique index on (tenant_id, ...) elsewhere would be fine; an index that merely
    *contains* tenant_id second is not, and would look like a pass to a name check.
    """
    name = "employees"
    index: Index | None = next(
        (
            candidate
            for candidate in Base.metadata.tables[name].indexes
            if candidate.name == tenant_index_name(name)
        ),
        None,
    )
    assert index is not None
    assert [column.name for column in index.columns] == ["tenant_id"]
    assert index.unique is False
