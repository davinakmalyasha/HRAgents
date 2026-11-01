# 09 — Sequence, Tracks, and Gates

**Status:** draft for implementation · **Branch:** `plan/desktop-rust-migration`
**Weeks are relative to project start (week 0); one week is five working days.** Dates are deliberately absent.

**Sequencing rule:** retire architecture risk first, deterministic correctness second, surface polish third, distribution last. Phases overlap only where this document says so; a gate never opens early.

## 1. Phases

| Phase | Weeks | Goal | Exit |
|---|---|---|---|
| 0. Decisions | 0–2 | Make irreversible choices once, in writing | ADRs accepted, scope frozen |
| 1. Vertical slice | 2–8 | Prove shell + SQLite + login + one domain journey | Gate 0, Gate 1 |
| 2. Deterministic parity | 6–22 | Port every decision-making path, with Python as oracle | Gates 2, 3, 4 |
| 3. UI/UX | 16–26 | Five surfaces, desktop interactions, accessibility | Gate 5 |
| 4. Hardening | 24–30 | Performance, security, recovery, migration | Gate 6 candidate |
| 5. Release/impact | 28–38 | Signed distribution, six-week pilot, removal of Python | Gate 6 + release at week 38 |

### Phase 0 — Decisions and ADRs (weeks 0–2)

**Deliverables:** accept the ten ADRs in 02 §14 (Tauri 2.12, direct IPC, SQLite/rusqlite, one company per DB, one `hr_operator` role, encryption, money type, `rig`, Python oracle, server boundary). Freeze scope from 00–08, pin the README version matrix, name the reference benchmark machine, approve the threat model and parity-corpus plan.

**Dependencies:** none. **Exit:** all ADRs accepted; no open decision in 11 blocks week 2; Python `oracle-0.19.0` tagged with a SHA-256 manifest; every risk has a named owner.

### Phase 1 — Vertical slice (weeks 2–8)

**Deliverables:** Cargo workspace and Tauri 2.12 shell; SQLite schema v1 (company, operator, employee, onboarding, audit, settings); migration runner; argon2id login, app lock, re-auth; typed IPC v1; audit append/verify; packaged development build on Windows and macOS; the first three parity fixtures.

**Dependencies:** Phase 0. **Exit:** Gate 0 at week 4; Gate 1 at week 8. The slice is vertical, not a platform with no product: a real employee is created, an onboarding plan is started, and the audit chain verifies after restart.

### Phase 2 — Deterministic parity (weeks 6–22)

**Deliverables:** ports in the exact dependency order fixed by 03 §3 (foundations, audit, auth, approvals, people, hiring, onboarding, leave, payroll, growth, offboarding, compliance, search, chat). Mandatory Rust AI port (extraction, structured output, Ask HR) using the existing prompts and schemas. Parity harness grows with every module. Operator-maintained rate tables carry a `verified` gate.

**Dependencies:** Gate 0; frozen corpus; Track D before Gate 2. **Exit:** Gate 2 at week 13, Gate 3 at week 19, Gate 4 at week 22.

### Phase 3 — UI/UX (weeks 16–26)

**Deliverables:** the five surfaces defined in 07; command palette and keyboard model; split view, bulk actions, drag-and-drop import; empty/loading/error states; EN/ID; accessibility; visual baselines; one-click demo company.

**Dependencies:** Gate 1 before identity and read models; Gate 3 before the pay surface; Gate 4 before final acceptance. **Exit:** Gate 5 at week 26. No surface is redesigned while its read model is still moving.

### Phase 4 — Hardening (weeks 24–30)

**Deliverables:** performance tuning to budgets; fuzzing; security review and dependency audit; backup/restore drill; Python data import; crash reporting; staged updater; migration rehearsal from every released schema; external penetration review.

**Dependencies:** Gate 4; Gate 5 before the Gate 6 candidate. **Exit:** Gate 6 candidate signed and installable, all budgets green.

### Phase 5 — Release and impact (weeks 28–38)

**Deliverables:** signed Windows installer, notarized macOS build, updater channels, a six-week pilot with 1–2 companies (weeks 32–38), demo dataset, operator documentation, support runbook, adoption metrics. Python source is deleted only after the first signed release and a frozen parity corpus.

**Dependencies:** Phase 4, legal/licensing review. **Exit:** Gate 6 at week 32; public release week 38.

## 2. Parallel tracks

| Track | Owns | Primary paths | Integration gates |
|---|---|---|---|
| A. Platform/Tauri | Shell, windows, single-instance, IPC transport, file dialogs, updater, signing, crash capture | `apps/desktop`, `hragents-ipc`, `scripts/release/` | G0, G5 process proof, G6 |
| B. Data/SQLite | Schema, migrations, FTS5, backup, import, encryption, integrity | `hragents-store`, `hragents-import`, `parity/db/` | G0, G1, G3, G4 |
| C. Rust core/domain | Models, scoring, policy, approvals, payroll, audit, documents, compliance | `hragents-core`, `hragents-app` | G1–G4 |
| D. AI | Provider adapters, prompts, structured output, redaction, evals; optional Rust-native research | `hragents-agents`, `prompts/`, `parity/llm/`, `evals/` | G2, G4; optional track |
| E. UI/UX | Five surfaces, design tokens, desktop interactions, i18n, accessibility | `web/`, `web/e2e/` | G1 visual, G2–G4 surfaces, G5 |
| F. Quality/docs | Parity harness, E2E, benchmarks, CI, ADRs, release docs | `parity/`, `hragents-parity`, `.github/workflows/`, `docs/` | All gates |

A track merges only when its slice passes the gate it targets. No track may invent a second source of truth to avoid waiting for another track.

## 3. Critical path

`ADRs → schema + IPC contract → auth/session → employee/onboarding → CV extraction + scoring + hiring case file → payroll parity → corpus freeze → Gate 5 cut-over → signed installer/updater → pilot`

UI work and the optional AI track hang off this path; neither may extend it. A four-week slip on Gate 2 or Gate 3 freezes scope and triggers the stop rules in 11 — Python is not deleted to protect a date.

## 4. Branching and merge order

| Branch | Scope | Lifetime | Merge condition |
|---|---|---|---|
| `plan/desktop-rust-migration` | Docs and ADRs only | Until Gate 0 | Docs reviewed; no product code |
| `feat/sqlite` | Schema, migrations, queries | ≤5 working days | Migration + fixture tests green |
| `feat/rust-core` | One domain slice per PR | ≤10 working days | Parity suite green for that slice |
| `feat/desktop-shell` | Tauri, IPC, login, packaging | ≤5 working days | Gate 0 smoke green |
| `feat/agents` | Providers, prompts, structured output | ≤5 working days | AI eval and schema parity green |
| `feat/ui-foundation`, `feat/ui-<domain>` | Shell, design system, one surface | ≤5 working days | Visual + a11y + journey green |
| `feat/quality` | Harness, CI, benchmarks | Continuous, small PRs | Never breaks `main` |

No branch is long-lived; `feat/rust-core` is a series of slices, not a parallel product. Rebase daily, squash-merge, keep `main` green. Per gate the merge order is: **schema PR → core PR → shell/IPC PR → agent PR → UI PR → quality evidence**. Feature flags live only until their gate and are deleted with the flag.

## 5. Gates

These are sequence gates. The parity checkpoints G0–G5 in 08 are evidence inside G2–G5, not a second gate system.

| Gate | Week | Proof — all must be true |
|---|---|---|
| G0 Shell + DB + login | 4 | Packaged build starts on Win/mac; creates an encrypted DB; login, lock, unlock, logout, re-auth; audit verifies after restart; no listening port |
| G1 Employee/onboarding | 8 | Employee created, onboarding plan started and completed, audited receipt; parity fixture matches Python; Python not invoked |
| G2 Hiring case file | 13 | CV → extraction → score → evidence → review → rejection sign-off; score reproducible; no LLM in the decision path |
| G3 Payroll | 19 | 1,000-employee run matches Python to the sen; leave/attendance inputs reconcile; verified rate tables; sign-off and export; run immutable |
| G4 Docs/compliance | 22 | Leave balances and approvals, document requests, retention, erasure, consent, audit export, policy chat with citations all pass |
| G5 No Python | 26 | Five journeys pass on a packaged build; full parity suite green; no Python binary, sidecar, or package in the bundle; source archived |
| G6 Signed installer/update/backup | 32 | Signed installer, notarized macOS build, signed staged updater, backup/restore drill, rollback rehearsal |

## 6. Optional Rust-native AI track

Weeks 16–30, off the critical path. The **mandatory** port in Phase 2 preserves the existing prompts and schemas; this track is the optional optimization that replaces the adapter internals. **Entry:** Gate 2 extraction parity. **Scope:** `rig`-based agents, multi-provider routing, Ollama/local models, streaming, `sqlite-vec` retrieval, prompt caching, eval dashboard. **Exit:** quality equal or better on the frozen eval set, extraction p95 < 15 s, zero PII egress without redaction. If it slips, ship the parity AI port; this track never gates G5 or G6.

## 7. What not to do

- **No big-bang rewrite.** Every merge is a working vertical slice with a passing journey.
- **No UI redesign before identity and read models exist.** Surface work follows Gate 1; pay follows Gate 3.
- **No Rust-native AI work that blocks deterministic parity.** It is an optimization, not a prerequisite.
- **No dual-write, hidden Python sidecar, or localhost HTTP bridge.** That is a second runtime to secure and debug.
- **No schema edit without a migration and fixture; no edit to a computed payroll run.** Corrections supersede with a reason.
- **No release before G5, and no deletion of Python before the parity corpus is frozen and signed.**
