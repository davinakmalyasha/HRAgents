# 02 — Target Architecture

**Status:** locked for the desktop edition · **Prereqs:** [`00-product-scope.md`](00-product-scope.md)

---

## 1. One diagram

```text
┌────────────────────────────────────────────────────────────────────┐
│ Tauri 2.12 application                                             │
│                                                                    │
│  ┌──────────────────────────────┐    typed IPC    ┌─────────────┐  │
│  │ React 19 + Vite + TypeScript │ ◄─────────────► │ Rust core   │  │
│  │ Windows WebView2 / WKWebView │   tauri-specta  │ (in-process)│  │
│  └──────────────────────────────┘                 └──────┬──────┘  │
│                                                          │         │
│                                                   ┌──────▼──────┐  │
│                                                   │ SQLite 3.54 │  │
│                                                   │ one file /  │  │
│                                                   │ one company │  │
│                                                   └─────────────┘  │
│                                                                    │
│  Tokio background jobs: reminders, IMAP poll, outbox, backups,     │
│  payroll compute, retention sweep, update check                    │
└────────────────────────────────────────────────────────────────────┘

External network (only when configured):
  LLM provider  ·  SMTP  ·  IMAP  ·  WhatsApp wa.me / Cloud API  ·  ICS
```

There is **no localhost HTTP server, no Python sidecar, no Docker, no Postgres, no
Redis, and no MinIO**. The Rust core is linked into the Tauri process. The frontend
talks to it through typed Tauri commands and events.

---

## 2. Why this architecture

| Requirement | Consequence |
|---|---|
| Maximum performance | No HTTP hop, no Python runtime, no container overhead; direct IPC and SQLite |
| Non-technical HR install | One signed installer, no server, no ports, no Docker |
| Sensitive data stays local | One encrypted database file; no SaaS; no telemetry by default |
| Named-human audit | Rust core knows the unlocked operator session; commands cannot act without it |
| Offline-first | Core records, payroll, and audit work with no network; only LLM/email degrade |
| One company per install | No tenant_id, no RLS, no per-tenant migrations |
| Future server edition | Core is a library; an optional Axum adapter can expose the same commands over HTTP |

The thesis does not change. The runtime gets simpler and faster.

---

## 3. Workspace layout

```text
hragents/
├── rust/                          # Cargo workspace (1.99.1)
│   ├── Cargo.toml
│   ├── rust-toolchain.toml
│   ├── crates/
│   │   ├── hragents-core/         # domain: money, scoring, policy, audit, payroll
│   │   ├── hragents-store/        # SQLite, migrations, repositories, FTS5
│   │   ├── hragents-agents/       # LLM providers, prompts, structured outputs
│   │   ├── hragents-ipc/          # Tauri command definitions + tauri-specta
│   │   ├── hragents-api/          # optional Axum adapter (feature-gated)
│   │   ├── hragents-import/       # one-time import from Postgres/CSV/JSON
│   │   └── hragents-parity/       # golden-file parity harness (dev-only)
│   └── apps/
│       └── desktop/               # Tauri app, icons, installer config
├── web/                           # React UI, Vite, Tailwind
├── docs/                          # this plan + product docs
└── legacy/
    └── python/                    # reference implementation until Gate 5
```

Dependency direction is one-way:

```text
hragents-core  ←  hragents-store  ←  hragents-ipc  ←  apps/desktop
       ↑                ↑
  hragents-agents   hragents-import
```

`hragents-core` must not depend on Tauri, SQLite, React, or network clients. It is
pure domain logic and can be tested in milliseconds.

---

## 4. The Rust core

`hragents-core` owns the rules that must never depend on UI or infrastructure:

- Domain models: candidate, application, evaluation, job, employee, contract,
  document, leave, payroll, growth, offboarding, compliance, approval/decision,
  audit.
- Money as integer **sen** (1/100 IDR, `i64`) so the current 2-decimal Python
  arithmetic is preserved exactly; `rust_decimal` is only for ratios and
  multipliers. Rounding is explicit and tested.
- Deterministic scorer `S ∈ [0,1]^4`, k-run mean/σ, evidence references, rubric
  snapshots.
- Policy engine: consent halt, anomaly, calendar, auto-schedule, soft rejection,
  auto-reject, named-human gate.
- Priority ranker.
- Payroll arithmetic and invariants.
- Audit chain (SHA-256, canonical serialization, append-only).
- Auth/session primitives: operator, role, session state, re-auth requirement.
- Errors: `thiserror` enums, no string sniffing.

The core is synchronous and fast. Async belongs to I/O at the edges.

---

## 5. The store

`hragents-store` owns SQLite:

- One file per company, in the OS app-data directory.
- WAL mode, foreign keys, busy timeout, prepared statements.
- Forward-only migrations with a schema version.
- FTS5 indexes for people, candidates, jobs, documents, audit.
- Repository traits implemented for SQLite; in-memory implementations for tests.
- Backup/restore using the SQLite backup API.
- Optional SQLCipher encryption.
- No RLS, no tenant_id, no Postgres-specific SQL.

Details: [`04-sqlite-data.md`](04-sqlite-data.md).

---

## 6. The IPC boundary

The frontend never opens a database or reads a file directly. It calls typed
commands:

```rust
#[tauri::command]
async fn list_candidates(
    state: State<'_, AppState>,
    session: SessionGuard,
    query: CandidateQuery,
) -> Result<Page<CandidateSummary>, AppError>;
```

- `SessionGuard` proves an unlocked operator; it is injected by the Rust side, never
  passed from JavaScript.
- `AppError` is a tagged enum serialized as a stable `{ code, message, details }`.
- Every command is registered with `tauri-specta`, which generates TypeScript
  bindings and event types.
- Long-running work returns a job id and emits progress events; the UI subscribes
  through TanStack Query + Tauri events.
- No command accepts an actor id in its body. The actor comes from the session.

The optional `hragents-server` crate can expose the same command handlers over Axum
for a future team edition. It is not built into the desktop binary.

---

## 7. Background jobs

A small Tokio runtime inside the Tauri process runs:

- Reminder scheduler (approval SLA, onboarding steps, contract expiry, document
  expiry, review cycle deadlines).
- IMAP poll for candidate/employee replies.
- Outbox for email/WhatsApp drafts that HR approved.
- Backup scheduler (daily, verified).
- Retention/purge sweep.
- Payroll compute (CPU-bound; run on a blocking pool).
- Update check (opt-in).
- Audit chain verification (startup and on demand).

Jobs persist in a `jobs` table, with attempts and leases, so a crash does not lose
work. There is no external queue.

---

## 8. Data flow: hiring

```text
HR imports CV
  → Rust stores document + hash
  → job: extract (rig agent, k=3) → structured evidence
  → core: deterministic score + σ + flags
  → core: policy engine → gated / auto-schedule / manual
  → audit: every step
  → UI: Candidate case file with CV + evidence + score
  → HR: advance / reject with reason / offer / schedule / message
  → audit receipt
```

The LLM never sees the final decision. It extracts and drafts. The score is computed
in Rust from structured evidence.

## 9. Data flow: payroll

```text
HR creates run for period
  → core: load compensation + attendance + rate tables
  → core: compute lines, anomalies, totals
  → HR: review, fix blocking anomalies, re-compute
  → HR: submit → re-auth → approve
  → core: freeze run, audit
  → export XLSX packet / payslips
```

No payment execution. No network required.

## 10. Data flow: Ask HR

```text
HR asks a question
  → core: route (HR policy / hiring / payroll / people)
  → retrieve local policy chunks (FTS5 + local vectors)
  → rig agent answers with citations
  → UI: answer, sources, handoff buttons
  → HR can create a task/decision from the answer
```

RAG is for recall and Q&A only. It never computes scores or decides.

---

## 11. Performance budgets

| Metric | Target | How |
|---|---|---|
| Cold start to usable window | < 1.5 s | Rust core, no Python, lazy React routes |
| First contentful paint | < 500 ms after window | Preloaded shell, small entry bundle |
| IPC read p95 | < 20 ms | Prepared SQLite statements, indexed queries |
| IPC write p95 | < 50 ms | Single writer, WAL, batched transactions |
| Candidate list 10k | < 100 ms | Indexes + pagination + virtualized UI |
| Payroll 1,000 employees | < 2 s | Integer arithmetic, one transaction, parallel line compute |
| Audit verification 100k entries | < 1 s | Streaming SHA-256, sequential scan |
| Idle RAM | < 200 MB | No Electron, no Python, no Chromium bundle; WebView2 still has a cost |
| Installer size | < 35 MB | Tauri + Rust + SQLite; no Python/Node runtime |
| DB size, 10k candidates + 1k employees + 100k audit | < 250 MB | Normalized schema, compressed documents on disk |

Build profile:

```toml
[profile.release]
lto = "fat"
codegen-units = 1
panic = "abort"
strip = true
opt-level = 3
```

SQLite tuning and query budgets are in [`04-sqlite-data.md`](04-sqlite-data.md).

---

## 12. Security boundary

- The Tauri window is the only UI; no remote web content.
- CSP is locked down; no eval, no remote scripts.
- Commands require an unlocked operator session.
- SQLCipher (or OS-level encryption) protects the database at rest.
- Secrets live in the OS keychain, never in the DB or localStorage.
- Backups are encrypted and integrity-checked.
- Updates are signed; installers are signed/notarized.
- No telemetry by default; crash reports are opt-in and redacted.
- Logs redact PII and secrets.

Details: [`06-auth-security.md`](06-auth-security.md).

---

## 13. What is deliberately absent

- HTTP API for the desktop app.
- Python runtime.
- Docker/Compose.
- PostgreSQL, Redis, MinIO, Mailpit.
- Multi-tenant RLS.
- PWA/service worker.
- Inbound webhooks.
- MCP marketplace.
- Microservices.

If the product later needs a team edition, the Rust core is reused behind Axum and
Postgres. The desktop app does not grow a server.

---

## 14. Architecture decision records to write first

1. ADR-001: Tauri 2.12, not Electron and not Tauri 3.
2. ADR-002: Rust core with direct IPC, not a localhost HTTP server.
3. ADR-003: SQLite + rusqlite, not SQLx/Postgres for desktop.
4. ADR-004: one company per DB, no tenant/RLS.
5. ADR-005: one `hr_operator` role, multiple local accounts, local login.
6. ADR-006: SQLCipher vs OS full-disk encryption.
7. ADR-007: integer sen (1/100 IDR) vs `rust_decimal` for money.
8. ADR-008: `rig` for LLM providers and structured outputs.
9. ADR-009: Python as reference oracle until Gate 5.
10. ADR-010: server edition boundary.

These are expanded in [`03-rust-backend.md`](03-rust-backend.md),
[`04-sqlite-data.md`](04-sqlite-data.md), and [`06-auth-security.md`](06-auth-security.md).
