"""Declarative base for all database tables."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Uuid, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from hr_agents.tenancy import DEFAULT_TENANT_ID

_TENANT_SERVER_DEFAULT = text(f"'{DEFAULT_TENANT_ID}'")


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
