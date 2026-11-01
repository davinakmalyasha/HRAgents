# 04 — SQLite data layer

**Status:** draft · **Target:** Tauri 2.12 + Rust · **Supersedes for the desktop edition:**
`docs/architecture/data-storage.md` §1–3 (PostgreSQL 16 + pgvector + Redis + MinIO). The
server edition keeps that stack.

## 1. Why SQLite

One company per install, one file: `%LOCALAPPDATA%\HRAgents\<company>\hragents.db`. No
server, no port, no `docker-compose.yml`, no Redis, no MinIO; backup is a file copy plus an
integrity check, restore is the reverse. The concurrency model *is* single-writer — one HR
operator, one machine — so MVCC, RLS and pooling buy nothing. With no IPC a lookup is a
B-tree probe in-process, and a 10k-candidate DB (~40 MB) fits in page cache.

**Why not embedded Postgres.** It ships a ~200 MB server, needs a supervised child process
and a private port, and its Windows fsync/upgrade story (`initdb`, `pg_dump` across versions,
a locked data directory) is the operational surface this edition deletes. Concurrency,
JSONB, pgvector and RLS are exactly what it removes.

## 2. Schema strategy

Drop `tenant_id` from all 54 tenant-scoped tables and delete `src/hr_agents/db/rls.py`
(54 columns, 54 indexes, 54 policies, the `app.tenant_id` dance). Keep `version` from
`TenantScoped` (`src/hr_agents/db/base.py:48`): two Tauri windows can still collide, and
`save_model` already refuses stale writes. New core tables: `company` (one row — the
`db_meta.company_id` identity from `03-rust-backend.md` §8, plus legal name, NPWP, timezone,
currency), `operator` (username, Argon2id hash + salt, role `hr_operator`, optional
`employee_id`), `settings` (key, JSON value), plus `jobs`, `schema_migrations`, `backup_runs`,
`import_runs`.

Measured from `Base.metadata`: **55 tables, 54 tenant-scoped, 89 indexes** (the migration
brief's 45 is out of date). Mapping by module under `src/hr_agents/db/`:

| Source | Desktop fate |
|---|---|
| `tables.py` recruiting: candidates, jobs, applications, evaluations, evaluation_overrides, feedback_reports, schedule_proposals, scheduling_availability, rubric_versions, candidate_communications, candidate_replies, email_application_drafts | keep (12) |
| `tables.py`: conversations, messages | **merge** — thread = `(candidate_id, channel)` on `messages`; drop `conversations` |
| `tables.py`: candidate_documents | keep metadata; `content` BLOB → `documents/<sha256>` |
| `tables.py`: provider_settings, credential_registries, llm_usage, mcp_servers | keep (4) |
| `tables.py`: push_subscriptions | **drop** — use `tauri-plugin-notification` |
| `tables.py`: audit_log | keep; drop `tenant_id`, keep the `seq`/`prev_hash`/`entry_hash` chain (`src/hr_agents/db/audit.py`) |
| `people_tables.py`: employees, org_units, employee_documents, contracts, approvals, tasks, rate_tables, pending_approval_syncs | keep 7; last → `jobs` kind `approval.sync` |
| `payroll_tables.py`, `leave_tables.py`, `growth_tables.py` | keep (10) |
| `onboarding_`, `offboarding_`, `offers_tables.py` | keep (7) |
| `compliance_tables.py`: consent_records, retention_*, erasure_requests, breach_incidents, compliance_calendar_entries, purge_jobs | keep 6; `purge_jobs` → `jobs` |
| `workspace_tables.py`: chat_conversations, workspace_requests | keep |

55 − 4 (push, conversations, purge_jobs, pending_approval_syncs) = 51 kept, + 7 new →
**58 tables**; 35 non-tenant indexes survive.

## 3. Configuration

**Use `rusqlite` 0.41**, not SQLx 0.9 (closing open decision 1 in `03-rust-backend.md` §14):
it exposes the backup API, `bundled-sqlcipher-vendored-openssl`, static `sqlite-vec`
registration and `prepare_cached` directly. SQLx wraps the same blocking calls, has no
first-class backup API (you would `VACUUM INTO`, unsafe under SQLCipher), and needs `.sqlx`
metadata at build time. Run rusqlite in `spawn_blocking`; Tauri commands stay async.

```rust
PRAGMA page_size = 8192;          // before first write: 4 KiB wastes B-tree fanout
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;         // per connection, not persisted
PRAGMA busy_timeout = 5000;
PRAGMA cache_size = -65536;       // 64 MiB
PRAGMA mmap_size = 268435456;
PRAGMA temp_store = MEMORY;
PRAGMA journal_size_limit = 67108864;
PRAGMA wal_autocheckpoint = 2000; // ~16 MB
```

One writer: a Tokio `mpsc` channel into a connection-owning task. Readers: `deadpool-sqlite`,
4 connections (WAL readers never block the writer). Use `synchronous=FULL` for the payroll
sign-off transaction only — `NORMAL` survives an app crash but can lose the last commit on
power loss, acceptable everywhere except a signed payslip. Cache statements with
`prepare_cached`.

## 4. Migrations

`rusqlite_migration` over `include_str!`-embedded SQL in `src-tauri/migrations/`,
forward-only:

```sql
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL,
  checksum TEXT NOT NULL, applied_at INTEGER NOT NULL);
```

`PRAGMA user_version` is the fast path; the table is the audit trail. No `down` — an
irreversible migration ships a backup instead. Each migration runs in one transaction after
a pre-migration backup (§9); if the backup or `integrity_check` fails, the app refuses to
migrate. Tests create from empty at every version and migrate a fixture at each prior
`user_version`.

## 5. Type mapping

| Concept | Storage | Note |
|---|---|---|
| UUID | `TEXT` 36-char | Tauri/JS sends strings; BLOB(16) only past 1 GB |
| Instant | `INTEGER` epoch millis UTC | sortable, compact |
| Civil date | `TEXT` `YYYY-MM-DD` | hires, expiries, due dates |
| Money | `INTEGER` minor units (`*_sen`) | `Money` is 2-dp `ROUND_HALF_UP` (`src/hr_agents/models/money.py`), so ×100 is lossless |
| JSON | `TEXT` + `CHECK (json_valid(col))` | `json_extract` for hot fields |
| Enum | `TEXT` + `CHECK (col IN (...))` | mirrors `String(32)` + Pydantic |
| Boolean | `INTEGER` `CHECK (col IN (0,1))` | |
| Array | `TEXT` JSON | none native today; junction only if it becomes a filter |

Timestamps are UTC, rendered in `company.timezone`; `business_today()`
(`src/hr_agents/models/common.py:65`) becomes a `chrono-tz` helper, never
`Local::now().date_naive()`.

```sql
CREATE TABLE payroll_lines (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
  employee_id TEXT NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  gross_sen INTEGER NOT NULL CHECK (gross_sen >= 0),
  total_deductions_sen INTEGER NOT NULL CHECK (total_deductions_sen >= 0),
  net_sen INTEGER NOT NULL CHECK (net_sen >= 0),
  status TEXT NOT NULL CHECK (status IN ('computed','approved','paid')),
  UNIQUE (run_id, employee_id),
  CHECK (net_sen = gross_sen - total_deductions_sen)) STRICT;
```

`STRICT` everywhere: it rejects the float/string coercion that silently corrupts money. The
four `payroll_lines` identities in `src/hr_agents/db/payroll_tables.py` port verbatim.

## 6. Search

FTS5 external-content tables, trigger-synced:

```sql
CREATE VIRTUAL TABLE candidates_fts USING fts5(
  full_name, headline, profile_text, content='candidates', content_rowid='rowid',
  tokenize="unicode61 remove_diacritics 2", prefix='2 3');
CREATE TRIGGER candidates_ai AFTER INSERT ON candidates BEGIN
  INSERT INTO candidates_fts(rowid, full_name, headline, profile_text)
  VALUES (new.rowid, new.full_name, new.headline, new.profile_text); END;
-- UPDATE/DELETE use the FTS5 'delete' command with the old row, never a plain DELETE
```

Also `people_fts`, `jobs_fts`, `documents_fts`, `audit_fts`. Rank with
`bm25(candidates_fts, 10.0, 4.0, 1.0)`; return `snippet(..., '**','**','…',12)`. JSON
profiles get a generated `profile_text`, so FTS never parses JSON at query time. No
`LIKE '%…%'` on a user-facing path.

## 7. Vector / RAG

The corpus is small (hundreds to low thousands of chunks), so **brute-force cosine
in-process is the default**, not an extension. Store little-endian `f32` BLOBs in
`vectors(owner_kind, owner_id, model, dim, vec)`; 5k × 256 floats is 5 MB and a full scan is
~1.3 M multiply-adds — sub-millisecond with `rayon`. The embedder is already local
(`hash-bow-v1-256`, `src/hr_agents/knowledge/embeddings.py`).

`sqlite-vec` (`vec0`, `vec_distance_cosine`) is the upgrade past ~50k vectors: register it
with `sqlite3_auto_extension` at startup, not `load_extension` at query time, so the bundled
binary needs no filesystem path. If it fails to load, log once and fall back to the scan —
never fail startup. Re-embedding is a `jobs` kind `vectors.rebuild`: delete by `model`,
re-insert in batches, swap `settings.embedding_model` in one transaction. No pgvector.

## 8. Queue and scheduler

Redis and the `SKIP LOCKED` backend (`src/hr_agents/providers/queue/postgres.py`) collapse
into one table plus Tokio tasks:

```sql
CREATE TABLE jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL CHECK (json_valid(payload)),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','running','done','failed','cancelled')),
  run_after INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5, lease_until INTEGER, dedup_key TEXT UNIQUE,
  last_error TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL) STRICT;
CREATE INDEX ix_jobs_claim ON jobs(run_after) WHERE status = 'pending';

UPDATE jobs SET status='running', attempts=attempts+1, lease_until=?2, updated_at=?3
WHERE id = (SELECT id FROM jobs WHERE status='pending' AND run_after <= ?1
            ORDER BY run_after LIMIT 1) RETURNING *;   -- inside BEGIN IMMEDIATE
```

Workers are `tokio::spawn`ed behind a `Semaphore` sized by `settings.max_workers`; the
scheduler is a 30 s `interval`. On startup every `running` row is stale, so reset it to
`pending` and retry with backoff; past `max_attempts` → `failed`, surfaced in the dashboard.
Work due while the app was closed runs on next launch: reminders are late, never lost.

## 9. Backup and restore

Daily at first launch after the local date changes, plus every 6 hours: `PRAGMA
wal_checkpoint(TRUNCATE)` → `rusqlite::backup::Backup` to
`backups/hragents-<YYYYMMDD-HHMMSS>.db` (restartable, safe while running) →
`PRAGMA integrity_check` on the copy, deleted if it fails. The `documents/` tree is copied
into the same timestamped folder. Retain 14 daily + 3 monthly.

Restore: close the app (single-instance lock), move the live DB to
`hragents.corrupt-<ts>.db` — never delete — copy the backup in, `integrity_check`,
checkpoint. If the live DB fails at startup, open read-only, refuse to write, and offer the
newest backup that passes; corruption never triggers silent recovery.
`backup_runs(id, path, bytes, started_at, status, integrity_ok)` records it. Exports stay
`hragents-export/1` JSON (`src/hr_agents/services/export.py`) plus CSV/XLSX writers over the
same iterator.

## 10. Encryption

**Recommended default (resolves ADR-006): SQLCipher** (`bundled-sqlcipher-vendored-openssl`):
the file holds salaries, NPWP numbers and identity documents, and the threat is a stolen
laptop — OS full-disk encryption is an assumption the operator can disable, and a copied
`.db` bypasses it.

- Argon2id (64 MiB, t=3, p=1, matching `03-rust-backend.md` §8) over the login password + a
  16-byte salt. The salt and an optional wrapped key for auto-unlock live in the OS keychain;
  the raw key never touches disk. `PRAGMA key = "x'<hex>'"`, then `SELECT count(*) FROM
  sqlite_master` to force the first decrypt.
- Key storage: Windows Credential Manager via `keyring` (DPAPI). A printed recovery key at
  setup is mandatory — a forgotten password without one is unrecoverable data loss.
- Password change: rewrap MK (no DB rewrite); MK rotation uses `PRAGMA rekey` after a backup, with a progress dialog.
- Benchmark encrypted vs plain: expect 5–15 % on I/O-bound work, near-zero on cached reads.
  If a hot path breaks the §12 budgets, document encryption-off; the payroll default stays on.

## 11. Import

`hragents-import` CLI: (A) `hragents-export/1` JSON from the current app, streamed per table;
(B) direct Postgres via the `postgres` crate, `--postgres-url`, one read-only transaction;
(C) CSV/XLSX per entity with a column map.

Parse → validate against structs mirroring the Pydantic models → resolve FKs by natural key
(`employee_number`, `candidate.primary_email`) → **dry-run by default**: the import runs in a
transaction and `ROLLBACK`s, printing counts and every error with its source row. `--commit`
writes. Idempotency: `import_runs(id, source_hash, table, rows, status)` plus `ON CONFLICT
DO NOTHING` on natural keys, so re-running a file is a no-op. One audit entry per table with
`actor_type='import'`, file hash and row count.

## 12. Performance

```sql
CREATE INDEX ix_applications_job_priority ON applications(job_id, priority_score DESC);
CREATE INDEX ix_comm_queue ON candidate_communications(created_at) WHERE status IN ('queued','sending');
CREATE INDEX ix_leave_open ON leave_requests(employee_id, start_date) WHERE status = 'pending';
CREATE INDEX ix_tasks_due ON tasks(due_on) WHERE status <> 'done';
CREATE INDEX ix_audit_subject ON audit_log(subject_type, subject_id, seq DESC);
```

| Query | Budget |
|---|---|
| Candidate/person FTS over 10k rows | < 20 ms p95 |
| Application board, one job (500 rows) | < 10 ms |
| Dashboard counts (5 aggregates) | < 5 ms |
| Payroll, 1,000 employees (compute + write) | < 2 s |
| Audit page (50 rows) | < 5 ms |

Size at 10k candidates / 1k employees / 100k audit entries: candidates + profiles ≈ 40 MB,
evaluations ≈ 60 MB, audit + FTS ≈ 120 MB, payroll (24 runs × 1k lines) ≈ 12 MB, document
metadata ≈ 6 MB, indexes ≈ 40 MB → **≈ 300 MB**, documents excluded. Maintenance: `PRAGMA
optimize` on shutdown and after imports, `ANALYZE` after import, checkpoint in the backup
job, `incremental_vacuum(1000)` weekly; benchmark with `criterion` on generated fixtures.

## 13. Acceptance criteria

1. Fresh install creates 58 tables, `integrity_check` = `ok`, cold open < 300 ms.
2. Every migration applies from empty and from a fixture at each prior `user_version`.
3. Backup → delete live DB → restore gives identical counts and an audit chain whose
   `verify()` returns the same entry count.
4. `hragents-import` ingests 10,000 candidates + 1,000 employees; dry-run writes nothing;
   re-running the same file changes zero rows.
5. Search p95 < 20 ms over those rows.
6. A 1,000-employee payroll run completes in < 2 s and passes the four arithmetic checks.
7. `kill -9` mid-payroll leaves a DB that passes `integrity_check` with either the whole run
   or none of it; `jobs` recovers on next start.

## 14. Risks and open decisions

- **Single file, single point of failure.** WAL + daily backups + integrity gates mitigate;
  no PITR. Accept and document.
- **Synced/network folders** (OneDrive, SMB) break locking. Refuse to open outside
  `%LOCALAPPDATA%` except an explicit restored copy.
- **`synchronous=NORMAL`** can lose the last commit on power loss; payroll sign-off uses
  `FULL`, everything else accepts it.
- **SQLCipher + FTS5 + `sqlite-vec`** is three native surfaces in one binary. Pin versions
  and run §13 on all three platforms before release.
- **Documents vs DB atomicity**: content-addressed files reconcile by hash scan; a missing
  file is reported, never silently recreated.
- **Open**: merge `chat_conversations` into the candidate thread model? Keep
  `workspace_requests` with one workspace per install? Decide before the phase-2 freeze.
- **Open**: should `employee_documents` keep small PDFs (< 1 MB) as BLOBs?
