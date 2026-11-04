# HRAgents Desktop — Rust + Tauri + SQLite Migration

**Status:** implemented, in polish · **Branch:** `plan/desktop-rust-migration` · **Date:** 2026-11-02

This folder is the complete migration and polish plan for turning HRAgents from a
Python/FastAPI + React web application into a **desktop-first, single-operator HR
cockpit** built with **Tauri 2.12, a Rust backend, and SQLite**.

It is a rewrite of the runtime, not a rewrite of the product thesis:

> Agents extract and communicate. Deterministic code decides. A named HR operator
> gates every consequential outcome. Every decision lands on a tamper-evident audit
> chain.

The desktop edition keeps that thesis and removes everything that does not help one
HR person do repetitive, exhausting work.

---

## 1. The decision in one page

| Decision | Choice |
|---|---|
| Product form | Desktop application, one company per install |
| Buyer / user | HR only — one to three HR operators, same role |
| Login | Yes — local operator login, app lock, re-auth for consequential actions |
| Roles | One role: `hr_operator`. No employee, manager, finance, candidate, or admin roles |
| Shell | Tauri **2.12.x** (latest stable 2.x; Tauri 3 is not stable) |
| UI | React **19.3.1** + Vite **8.3.5** + TypeScript **7.0.2** + Tailwind **4.3.3** |
| Backend | Rust **1.99.1**, in-process with Tauri; no Python at runtime |
| Database | SQLite **3.54.1**, one file per company, WAL, FTS5; 47 single-company tables (5 FTS5 indexes) |
| IPC | Direct Tauri commands with typed TS wrappers; no localhost HTTP server. `tauri-specta` is the planned drift-killer once the command surface freezes. |
| AI | Rust-native agent layer (`rig` 0.46.x or latest stable) |
| Network | Only LLM, SMTP/IMAP, WhatsApp links/API, calendar ICS; no inbound webhooks |
| Distribution | **Free edition:** unsigned per-user Windows installer (no admin, no certificate, no paid account); macOS build optional. Auto-update disabled by design. |
| Cost | **Zero.** No paid services, no subscriptions, no hosted update server, no signing certificates, no telemetry |
| Performance | Rust core, direct IPC, SQLite, no Docker, no Python, no Redis, no Postgres |
| Non-goals | Multi-tenant SaaS, employee self-service, manager/finance logins, candidate portal, mobile/PWA, MCP marketplace, webhooks |

**Why desktop is coherent now:** the product is deliberately narrowed to the HR
operator's cockpit. If the product later needs employee or manager logins, inbound
WhatsApp webhooks, or multi-company tenancy, that is the **server edition** — not
this desktop edition.

---

## 2. Read this in order

| # | Document | What it answers |
|---|---|---|
| 00 | [`00-product-scope.md`](00-product-scope.md) | Who it is for, what is in/out, what "only HR" means, login model |
| 01 | [`01-current-features.md`](01-current-features.md) | Exhaustive inventory of the current product, with status |
| 02 | [`02-architecture.md`](02-architecture.md) | The target runtime: Tauri + Rust + SQLite, data flow, performance budgets |
| 03 | [`03-rust-backend.md`](03-rust-backend.md) | Rust workspace, domain modules, AI layer, parity strategy |
| 04 | [`04-sqlite-data.md`](04-sqlite-data.md) | Schema, migrations, FTS5, vectors, backup, encryption, import |
| 05 | [`05-tauri-desktop.md`](05-tauri-desktop.md) | Shell, IPC, packaging, updater, code signing, desktop UX |
| 06 | [`06-auth-security.md`](06-auth-security.md) | Login, operator role, session lock, named-human gate, threat model |
| 07 | [`07-ui-ux.md`](07-ui-ux.md) | Five surfaces, screen specs, design system, desktop interactions |
| 08 | [`08-feature-parity.md`](08-feature-parity.md) | Python → Rust parity matrix, cut/finish/hide, journey acceptance |
| 09 | [`09-sequence.md`](09-sequence.md) | Phases, tracks, branches, integration gates |
| 10 | [`10-quality.md`](10-quality.md) | Tests, parity harness, benchmarks, CI, release |
| 11 | [`11-risks.md`](11-risks.md) | Risk register, open decisions, non-goals |
| 12 | [`12-impact.md`](12-impact.md) | Positioning, demo, metrics, pilot |
| 13 | [`13-implementation-status.md`](13-implementation-status.md) | What is actually built, gate status, evidence, next tasks |
| 14 | [`14-release-drill.md`](14-release-drill.md) | Signing status, clean-VM checklist, backup/restore + rollback rehearsal |
| 15 | [`15-pilot.md`](15-pilot.md) | Six-week pilot plan, entry/exit criteria, metrics, support runbook |
| 16 | [`16-restore-drill.md`](16-restore-drill.md) | Backup/restore drill procedure, failure injection, sign-off |

The executive summary is [`../massive-polishment.md`](../massive-polishment.md).

---

## 3. What changes from the current product

### Keep

- Deterministic scoring with evidence references and σ/k-run agreement.
- Hash-chained audit log and named-human gates.
- Payroll arithmetic: BPJS, THR, PTKP, TER, overtime, minimum wage, no payment execution.
- Hiring pipeline, review, scheduling, offers, candidate communications.
- People, onboarding, leave, growth administration, offboarding, compliance.
- Ask HR policy chat with citations.
- English + Bahasa Indonesia.
- Design tokens, accessibility, and the "status always has icon + label" rule.

### Remove from this edition

- Employee self-service and employee login.
- Manager, finance, recruiter, and admin roles.
- Candidate portal.
- Multi-tenant RLS, tenant scoping, SaaS billing.
- Docker, Postgres, Redis, MinIO, Mailpit, worker/scheduler/messaging containers.
- PWA, push notifications, service worker.
- Inbound email/WhatsApp/Telegram webhooks.
- MCP marketplace and developer connector catalog.
- Storybook, paper, research pages, build-plan pages from the user-facing product.
- UUIDs, Board/Queue/Chat internals, and demo-only controls in the UI.

### Add

- Local operator login, app lock, and re-auth for payroll/erasure/rejection overrides.
- Candidate profile and CV viewer.
- Document preview/download.
- Employee compensation and payroll profile.
- Global search over people, candidates, jobs, documents, and audit.
- Backup/restore, update, and crash diagnostics.
- A one-click demo company that reaches the value moment in under five minutes.

---

## 4. Version matrix (latest stable, 2026-11-01)

Pin exact versions in `Cargo.lock`, `package-lock.json`, and the Tauri config. Run
`cargo outdated` and `npm outdated` at scaffold time; do not float majors.

| Layer | Version | Notes |
|---|---|---|
| Rust | 1.99.1 | Tauri 2.12 MSRV is 1.90; 1.99.1 is current stable |
| Tauri | 2.12.x | Latest stable 2.x; no stable Tauri 3 |
| `@tauri-apps/api` | 2.12.x | Must match the Tauri minor line |
| SQLite | 3.54.1 | Bundled via `rusqlite` |
| `rusqlite` | 0.41.x | `bundled`, `backup`, `functions`, `sqlcipher` features |
| React | 19.3.1 | Latest 19.3 patch |
| Vite | 8.3.5 | Latest stable |
| TypeScript | 7.0.2 | Latest stable; check ESLint/TS plugin compatibility |
| Tailwind CSS | 4.3.3 | CSS-first config |
| TanStack Query | 5.x | Latest 5.x |
| Zustand | — | Not used: TanStack Query plus local state is enough for one window |
| react-router | — | Removed: five surfaces are local state, not URLs |
| i18next / react-i18next | — | Not used: English-only cockpit, copy lives in components |
| Axum | 0.8.x | Only for the optional server edition |
| SQLx | — | Not used: rusqlite was chosen for synchronous single-connection access |
| `rig` | 0.46.x | Rust LLM agents/providers |
| `tauri-specta` | 2.x (planned) | Typed IPC bindings; adopt once the command surface freezes |
| `tokio` | 1.x | Async runtime for network/jobs |
| `serde` / `schemars` | 1.x | Serialization and structured-output schemas |
| `argon2` | latest 0.5.x | Password hashing |
| `sha2` | 0.10.x | Audit chain |
| `rust_decimal` | — | Not used: integer sen covers every amount exactly |
| `rust_xlsxwriter` | latest | Payroll/export packets |
| `rusqlite` + SQLCipher | 0.41 / 4.x | Encrypted local database |
| `chacha20poly1305` | 0.10 | Encrypted uploaded documents |
| `windows-sys` (DPAPI) | 0.59 | Key-file protection on Windows; mode 0600 elsewhere |
| `lettre` / `async-imap` | — | Not yet: send/poll stay manual, so no mail credentials are required |
| `icalendar` | — | Not yet: interview slots are proposed in-app |
| `sqlite-vec` | — | Not used: FTS5 plus keyword retrieval is sufficient offline |

Tauri 3 is explicitly **not** used. If a stable Tauri 3 ships during the project,
upgrade only after the desktop shell is isolated behind a version-pinned adapter and
the updater/signing pipeline has been re-tested.

---

## 5. Branch and delivery strategy

- `plan/desktop-rust-migration` — this documentation.
- `feat/rust-core` — domain models, scoring, policy, audit, payroll.
- `feat/sqlite` — schema, migrations, FTS5, backup, import.
- `feat/desktop-shell` — Tauri, IPC, login, updater, packaging.
- `feat/agents-rust` — Rust LLM layer and prompt parity.
- `feat/ui-foundation` — five-surface shell and design system.
- `feat/ui-<domain>` — hiring, people, pay, ask, settings.
- `feat/quality` — parity harness, E2E, benchmarks, CI.

No long-lived branches. Every merge gate is a working vertical slice, not a pile of
unused modules. The Python implementation stays in the repository as the reference
oracle until the Rust parity gates pass; it is removed from the runtime at Gate 5.

---

## 6. Definition of "perfect" for this edition

A screen is done only when it answers four questions without a click:

1. **Whose is this?** Name, role, company, job.
2. **What state is it in?** Status, age, owner, next deadline.
3. **What can I do next?** One primary action, plus safe secondary actions.
4. **Who decided last, and why?** An audit receipt with actor, time, reason, and payload.

A journey is done only when it passes end-to-end on a packaged build, with a real
SQLite file, a locked/unlocked session, and an audit chain that verifies after
restart.

The five journeys are in [`08-feature-parity.md`](08-feature-parity.md).
