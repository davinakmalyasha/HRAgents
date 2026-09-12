# ADR 0006 — Single schema with `tenant_id` and forced row-level security

**Status:** accepted · **Date:** 2026-09-12

## Context

The product must be self-hostable by a single company **and** run as a managed
multi-tenant service from the same codebase. Multi-tenant isolation done only in
application code fails open: one missed `WHERE tenant_id = ...` leaks another
company's employee data. The platform also already ships a Postgres system of
record with Alembic migrations and a sync store-adapter layer (ADR 0005).

## Decision

- **One schema, one column dimension.** Every domain table gains a
  `tenant_id UUID NOT NULL` (31 tables) via a `TenantScoped` mixin; existing
  rows are backfilled to `DEFAULT_TENANT_ID` (`…0001`). No schema-per-tenant.
- **PostgreSQL row-level security is the enforcement point.** Migration `0006`
  enables `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` and creates a
  `tenant_isolation` policy per table with `USING` **and** `WITH CHECK`.
- **Fail closed by default.** The policy resolves to
  `tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), '')::uuid, DEFAULT_TENANT_ID)`.
  An unset setting behaves as the default tenant: single-tenant installs work
  with zero configuration, and a misconfigured multi-tenant install sees only
  the default tenant — never another tenant's rows.
- **Tenant is set per transaction.** `sync_session_scope(..., tenant_id=…)`
  issues `set_config('app.tenant_id', …, true)`. Application inserts default to
  the default tenant; the RLS `WITH CHECK` still blocks cross-tenant writes.
- **Tests (and any deployment) must use a non-superuser role.** Superusers and
  `BYPASSRLS` roles bypass RLS even with `FORCE`; `scripts/prepare_test_db.py`
  creates a non-superuser role for the CI adapter suite.

## Consequences

- Isolation does not depend on application correctness; a forgotten filter
  returns nothing instead of another tenant's data.
- The default-tenant fallback keeps the self-host path unchanged and keeps
  existing tests valid (they run as the default tenant).
- Every future table must inherit `TenantScoped` and be added to the migration;
  `tests/db/test_rls.py` proves reads and writes are fenced.
- Superuser connections (for example, the compose `hragents` user) bypass RLS;
  production deployments for multiple tenants must connect as the restricted
  application role. This is tracked in the polish backlog and the ops phase.
- Tenant-aware connection routing (per-tenant pools/secrets) and RLS policy
  auditing remain open work; the current slice makes isolation structural.
