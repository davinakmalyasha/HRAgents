"""Tenant isolation SQL for PostgreSQL row-level security.

One policy per table, applied to the table owner as well (``FORCE``). An unset
``app.tenant_id`` behaves as the default tenant, so a single-tenant install
works without configuration and a misconfigured multi-tenant install fails
closed (it sees only the default tenant, never another tenant's rows).
"""

from __future__ import annotations

from hr_agents.tenancy import DEFAULT_TENANT_ID

POLICY_NAME = "tenant_isolation"

TENANT_POLICY_EXPR = (
    "tenant_id = COALESCE("
    "NULLIF(current_setting('app.tenant_id', true), '')::uuid, "
    f"'{DEFAULT_TENANT_ID}'::uuid)"
)


def enable_tenant_rls_sql(table: str) -> list[str]:
    """DDL enabling row-level security and the tenant policy for one table."""
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        (
            f"CREATE POLICY {POLICY_NAME} ON {table} "
            f"USING ({TENANT_POLICY_EXPR}) WITH CHECK ({TENANT_POLICY_EXPR})"
        ),
    ]


def disable_tenant_rls_sql(table: str) -> list[str]:
    """DDL removing the tenant policy and disabling row-level security."""
    return [
        f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table}",
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
    ]
