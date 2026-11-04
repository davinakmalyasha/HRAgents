# ADR 0010 — One company per install; no `tenant_id` and no row-level security in the desktop schema

**Status:** accepted · **Date:** 2026-11-01

## Context

ADR 0006 chose one schema with `tenant_id` and forced row-level security so a managed
multi-tenant service and a self-hosted install could share a codebase. The desktop edition is
one company on one machine in one file, operated by one to three people. The current schema has
54 tenant-scoped tables — 54 columns, 54 indexes, 54 policies and a per-transaction
`set_config('app.tenant_id', …)` dance. With exactly one company that machinery isolates
nothing, taxes every query, and adds a place to fail open.

## Decision

- Drop `tenant_id` from all 54 tenant-scoped tables and delete the RLS module and policies from
  the desktop schema.
- Company identity is a single `company` row; `db_meta.company_id` is retained for backup
  identity only, never for filtering.
- Keep `version` from `TenantScoped` and the `StaleWrite` error: two Tauri windows can still
  collide on a stale write.
- No schema-per-tenant, no tenant-aware pooling, no `Permission` or tenancy module.
- ADR 0006 remains authoritative for the server edition. This ADR narrows it for the desktop
  edition; it does not delete the decision.
- Existing data arrives through `hragents-import` (Postgres export, `hragents-export/1` JSON,
  CSV/XLSX) with dry-run by default and natural-key idempotency.

## Consequences

Easier: 54 columns, indexes and policies disappear; queries lose a predicate; there is no
non-superuser role trap in tests; backup identity is explicit rather than inferred.

Harder: the two editions now have divergent schema lineages, so a server edition cannot consume
desktop migrations unchanged; a desktop install can never hold a second company without a new
file and a redesign; import becomes the only migration path and must be rehearsed against every
released schema.

Out of scope: multi-tenant RLS, schema-per-tenant, cross-tenant administration, SaaS billing,
multi-company switching, tenant-aware connection routing.

Guards: a schema snapshot test fails if `tenant_id` or an RLS policy reappears; the import
dry-run asserts one `company_id` per file and rolls back; the Gate-5 journeys run on a database
that has no tenant column.
