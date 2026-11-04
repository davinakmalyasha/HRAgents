# Massive Polishment — HRAgents Desktop

**Status:** approved direction, draft for implementation · **Date:** 2026-11-01
**Detailed plan:** [`docs/plan/desktop-migration/`](desktop-migration/README.md)

This is the top-level plan for the biggest change in the project: moving HRAgents
from a Python/FastAPI + React web app to a **desktop-first, HR-only cockpit** built
with **Tauri 2.12, a Rust backend, and SQLite**.

It is not a visual refresh. It is a runtime rewrite plus a product narrowing. The
safety thesis stays; the architecture and scope change.

---

## 1. The decision

| Question | Answer |
|---|---|
| Web or desktop? | **Desktop.** One HR operator per company; local data; no server. |
| Tauri version? | **Tauri 2.12.x** — latest stable 2.x. Tauri 3 is not stable. |
| Backend? | **Rust 1.99.1**, in-process with Tauri. No Python at runtime. |
| Database? | **SQLite 3.54.1**, one file per company. No Postgres, Redis, MinIO. |
| UI? | **React 19.3.1 + Vite 8.3.5 + TypeScript 7.0.2 + Tailwind 4.3.3.** |
| Login? | **Yes** — local HR operator login, app lock, re-auth for consequential actions. |
| Roles? | **One:** `hr_operator`. No employee, manager, finance, candidate, or admin roles. |
| Multi-user? | 1–3 HR operators, same role, each named in the audit chain. No RBAC matrix. |
| Multi-tenant? | No. One company per install. |
| Deployment? | **Free edition:** unsigned per-user Windows installer (no admin, no paid account), macOS optional, auto-update off by design. |
| Performance? | Direct Rust IPC, SQLite, no Python/Docker/HTTP hop. Target cold start <1.5s, installer <35MB. |

**Why desktop is right now:** the product is deliberately a single-operator HR
cockpit. The buyer is the HR person, the data is sensitive, and the repetitive work
is local. Employee/manager portals, inbound webhooks, and multi-company tenancy are
a future **server edition**, not this product.

---

## 2. What “only HR” means

The product helps HR do repetitive, exhausting work:

- Read and organize CVs.
- Chase documents and onboarding steps.
- Keep employee records, contracts, and expiry dates straight.
- Record leave requests and balances.
- Assemble payroll, check anomalies, verify statutory rates, export a packet.
- Administer review cycles and collect forms.
- Run offboarding checklists.
- Answer policy questions with citations.
- Prove what happened with an audit chain.

It does **not** include employee self-service, manager logins, finance approvals,
candidate accounts, or a company-wide HRIS. Those are out of scope.

Login is included because the app holds payroll and identity documents, and because
every consequential action needs a named HR operator. The login is local, not a
server account. There is no email password reset, SSO, or role matrix.

---

## 3. What changes

### Keep

- Deterministic scoring, evidence references, σ/k-run agreement.
- Hash-chained audit log and named-human gates.
- Payroll arithmetic: BPJS, THR, PTKP, TER, overtime, minimum wage.
- Hiring pipeline, review, scheduling, offers, communications, feedback.
- People, onboarding, leave, growth admin, offboarding, compliance.
- Ask HR with citations.
- English + Bahasa Indonesia.
- Design tokens and accessibility discipline.

### Remove from this edition

- Employee/manager/finance/recruiter/admin roles.
- Employee self-service and candidate portal.
- Multi-tenant RLS and SaaS billing.
- Docker, Postgres, Redis, MinIO, Mailpit, worker/scheduler/messaging containers.
- PWA, push, service worker.
- Inbound WhatsApp/Telegram/email webhooks.
- MCP marketplace and connector catalog.
- Storybook and demo-only controls.
- UUIDs and Board/Queue/Chat UI.

### Add

- Candidate profile and CV viewer.
- Document preview/download.
- Employee compensation and payroll profile (JKK, dependents, PTKP, bank).
- Payroll inputs UI and a real THR/final-settlement path.
- Global search.
- Login, app lock, re-auth.
- Backup/restore, update, diagnostics.
- One-click demo company.

---

## 4. The target experience

Five surfaces, not ten workspaces:

```
Today     — every decision, deadline, expiring record, agent activity
Hire      — pipeline, candidates, jobs, import, interviews, offers
People    — directory, person profile, onboarding, leave, growth, offboarding
Pay       — payroll runs, compensation, rates, compliance
Ask       — policy chat with citations and handoffs
Settings  — company, operators, providers, backup, updates, audit
```

Every screen answers: **whose is this, what state is it in, what can I do next, and
who decided last?**

Every decision produces an audit receipt. Every list has a real empty state and a
primary action. No UUIDs. No dead links. No “Queue” tab hiding the only button.

---

## 5. The stack, with latest versions

| Layer | Choice | Version |
|---|---|---|
| Language | Rust | 1.99.1 |
| Desktop shell | Tauri | 2.12.x |
| Database | SQLite | 3.54.1 |
| SQLite access | `rusqlite` | 0.41.x |
| UI | React | 19.3.1 |
| Build | Vite | 8.3.5 |
| Types | TypeScript | 7.0.2 |
| Styles | Tailwind CSS | 4.3.3 |
| Server state | TanStack Query | 5.x |
| UI state | Zustand | 5.x |
| Router | react-router | 8.x |
| i18n | i18next / react-i18next | 26.x / 17.x |
| LLM agents | `rig` | 0.46.x |
| IPC types | `tauri-specta` | 2.x |
| Async | Tokio | 1.x |
| Serialization | serde / schemars | 1.x |
| Passwords | Argon2id (`argon2`) | 0.5.x |
| Audit | SHA-256 (`sha2`) | 0.10.x |
| Optional server | Axum | 0.8.x |
| Optional SQL layer | SQLx | 0.9.x |

Pin exact versions in `Cargo.lock` and `package-lock.json`. Update deliberately, not
by floating ranges. Tauri 3 is not used until it is stable and the shell adapter is
re-tested.

---

## 6. The sequence

A full Rust rewrite is not a two-week polish. The critical path is **~36–38 weeks**
for one focused team; parallel tracks can compress wall-clock, but they cannot skip
the gates. The detailed plan, tracks, branches, and gate evidence is
[`09-sequence.md`](desktop-migration/09-sequence.md).

| Phase | Weeks | Goal | Gate |
|---|---|---|---|
| 0. Decisions and ADRs | 0–2 | Lock runtime, scope, versions, parity oracle | ADRs accepted; scope frozen |
| 1. Vertical slice | 2–8 | Tauri shell + SQLite + login + employee/onboarding | G0 shell/DB/login; G1 employee/onboarding |
| 2. Deterministic parity | 6–22 | Money, audit, approvals, scoring, hiring, payroll, people, compliance | G2 hiring; G3 payroll; G4 docs/compliance |
| 3. UI/UX | 16–26 | Five surfaces, desktop interactions, a11y, i18n | G5 no-Python packaged build |
| 4. Hardening | 24–30 | Performance, security, backup/restore, import, crash handling | G6 candidate |
| 5. Release and impact | 28–38 | Signed installer, updater, six-week pilot, docs, metrics | G6 + release at week 38 |

**What is parallel:** UI/UX can start once the read models are stable (after G1).
The Rust AI port can start once extraction parity is proven (after G2). Quality and
docs run continuously.

**What is not parallel:** you cannot cut over to Rust before deterministic parity;
you cannot delete Python before the parity corpus is frozen; you cannot ship before
the signed installer, backup/restore drill, and audit verification pass.

**Phase 6 — impact (after the first signed release):** two-company pilot,
before/after metrics, case study, public docs, demo video, landing page. A server
edition is only considered if pilot demand proves it.

---

## 7. Parallel workstreams

| Track | Owns | Main outputs |
|---|---|---|
| A. Desktop platform | Tauri shell, IPC, login, updater, packaging | Installer, typed IPC, app lock |
| B. Data | SQLite schema, migrations, FTS5, backup, encryption, import | Store crate, migration tests |
| C. Rust core | Domain, scoring, policy, audit, payroll | Parity-tested core |
| D. AI | `rig` providers, prompts, structured outputs, fixtures | Five agents in Rust |
| E. UI/UX | Five surfaces, design system, screen specs | Polished, named, actionable UI |
| F. Quality/impact | Parity harness, E2E, benchmarks, docs, pilot | Gates, evidence, release |

Integration gates are owned by the whole team, not a single track. No track merges a
pile of unused modules; every merge is a working vertical slice.

---

## 8. Definition of done

A screen is done only when it answers four questions without a click:

1. **Whose is this?** Name, role, company, job.
2. **What state is it in?** Status, age, owner, deadline.
3. **What can I do next?** One primary action.
4. **Who decided last, and why?** An audit receipt.

A journey is done only when it passes end-to-end on a packaged build, with a real
SQLite file, a locked/unlocked session, and an audit chain that verifies after
restart.

The five journeys:

1. First run/login → company → employee → onboarding.
2. Import candidate → CV → evaluation → gated rejection → audit receipt.
3. Record leave → balance → decide → calendar.
4. Payroll run → inputs → compute → approve → export.
5. Document upload → preview → verify → audit.

---

## 9. What would make this fail

- Rewriting the UI before the candidate/document/payroll read-write paths exist.
- Porting Python bugs (THR/final pay, JKK/dependents, consent withdrawal) instead of
  fixing them.
- Building a “full HR suite” again instead of the HR cockpit.
- Shipping a desktop app that still needs a terminal, a server, or a cloud key.
- Calling a build “done” because the API compiles, not because a journey passes.
- Adding employee/manager logins back into this edition.

The mitigation is in [`11-risks.md`](desktop-migration/11-risks.md).

---

## 10. The one-line summary

**HRAgents Desktop: the audit-grade HR cockpit for the HR department of one — Rust,
Tauri, SQLite, local login, no infrastructure, every decision receipted.**
