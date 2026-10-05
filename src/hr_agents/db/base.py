"""Declarative base for all domain tables.

Every tenant-scoped table gets an index on ``tenant_id``, enforced here rather than by
convention. Row-level security adds ``tenant_id = ...`` to *every* query, so without that
index the isolation layer is a sequential scan of the whole table on every read: the
security mechanism sets the performance floor for the entire database. Writing the index
by hand on every table is one chance to forget per table, which is exactly how the schema
went fourteen migrations with none -- ``docs/plan/remaining-work.md`` tracked it as a
known defect the whole time.

A mixin cannot supply ``__table_args__``, so the indexes are added from
:func:`ensure_tenant_indexes` once the mappers are configured. It runs automatically on
``after_configured`` and is also exported for callers that need the metadata to be final
before generating DDL -- Alembic's ``check`` and the SQLite test harness both do.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Index, Table, Uuid, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Mapper, mapped_column

from hr_agents.tenancy import DEFAULT_TENANT_ID

_TENANT_SERVER_DEFAULT = text(f"'{DEFAULT_TENANT_ID}'")


def tenant_index_name(table_name: str) -> str:
    """``ix_<table>_tenant`` -- the one index every tenant-scoped table must have."""
    return f"ix_{table_name}_tenant"


class TenantScoped:
    """Mixin adding the tenant column to every domain table.

    Application inserts default to the self-host tenant; the Postgres RLS
    policies in ``db/rls.py`` restrict visibility per tenant.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        default=DEFAULT_TENANT_ID,
        server_default=_TENANT_SERVER_DEFAULT,
    )


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""


def ensure_tenant_indexes() -> list[str]:
    """Add ``ix_<table>_tenant`` to every tenant-scoped table. Idempotent.

    Returns the names of the tables that gained the index on this call, which is empty
    on every call after the first. Exposed rather than only hooked so that a caller
    generating DDL can be certain the metadata is final -- ``alembic check`` fails
    otherwise, and it runs in CI.
    """
    added: list[str] = []
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        # `local_table` is typed as a FromClause; only a single-table mapper has the
        # two attributes used here, and the guard is what narrows it.
        if not isinstance(table, Table) or "tenant_id" not in table.c:
            continue
        name = tenant_index_name(table.name)
        # `table.indexes` holds Index *objects*, so membership is by name.
        if any(index.name == name for index in table.indexes):
            continue
        table.append_constraint(Index(name, table.c.tenant_id))
        added.append(table.name)
    return added


@event.listens_for(Mapper, "after_configured")
def _index_tenant_columns_on_configure() -> None:
    ensure_tenant_indexes()
