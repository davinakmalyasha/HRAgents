# ADR 0009 — SQLite 3.54.1 through rusqlite 0.41, one database file per company

**Status:** accepted · **Date:** 2026-11-01

## Context

The current system runs Postgres 16 with pgvector, Redis and MinIO. The desktop edition has one
writer, one machine and one company; MVCC, row-level security and connection pooling buy
nothing there. Embedded Postgres would ship a ~200 MB server, a supervised child process, a
private port and a Windows fsync/upgrade story. Between drivers, `rusqlite` 0.41 exposes the
backup API, bundled SQLCipher, static `sqlite-vec` registration and `prepare_cached`; SQLx 0.9
has no first-class backup API (you would `VACUUM INTO`, unsafe under SQLCipher) and needs
`.sqlx` metadata at build time.

## Decision

- Bundle SQLite **3.54.1** via `rusqlite` 0.41 (`bundled`, `backup`, `functions`, `blob`).
- One file per company at `%LOCALAPPDATA%\HRAgents\<company>\hragents.db`.
- Pragmas: `page_size=8192` before the first write, WAL, `synchronous=NORMAL` (FULL for the
  payroll sign-off transaction only), `foreign_keys=ON`, `busy_timeout=5000`,
  `cache_size=-65536`, `mmap_size=256 MB`, `temp_store=MEMORY`.
- One writer task fed by an mpsc channel; four pooled readers via `deadpool-sqlite`.
- `rusqlite_migration` with forward-only SQL, a `schema_migrations` checksum table and a
  pre-migration backup. Each migration runs in one transaction.
- Tables are `STRICT`; enums and booleans use `CHECK`; JSON is `TEXT` with `json_valid`.
- No Postgres-specific SQL, no `tenant_id`, no RLS (ADR 0010).

## Consequences

Easier: backup is a checkpoint plus the online backup API plus `integrity_check`; there is no
server, port, Redis queue or MinIO; a 10k-candidate database is ~40 MB and fits in page cache;
migrations are one transaction instead of an Alembic environment.

Harder: a single file is a single point of failure with no point-in-time recovery; the writer
serializes all writes; OneDrive/SMB folders break locking, so the app refuses to open outside
the app-data root; `synchronous=NORMAL` can lose the last commit on power loss; SQLCipher, FTS5
and `sqlite-vec` are three native surfaces in one binary.

Out of scope: Postgres, pgvector, Redis, MinIO, SQLx for the desktop edition, schema-per-tenant.

Guards: `04-sqlite-data.md` §13 — a fresh install creates 58 tables with `integrity_check = ok`
and opens cold in under 300 ms; migrations apply from empty and from every prior `user_version`;
`kill -9` mid-payroll leaves either the whole run or none; a backup/restore drill runs each
release.
