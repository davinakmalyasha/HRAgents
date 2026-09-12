"""Tenancy: every row belongs to exactly one tenant.

The self-hosted product runs as the default tenant; a managed deployment
overrides the tenant per request. Isolation is enforced in Postgres with
row-level security (see ``db/rls.py`` and ADR 0006), not only in application
code.
"""

from __future__ import annotations

from uuid import UUID

DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
"""Tenant used by single-tenant installs and for rows created before tenancy."""


def default_tenant_id() -> UUID:
    """Column default factory (stable for migrations and tests)."""
    return DEFAULT_TENANT_ID
