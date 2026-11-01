# 13 — Implementation Status

**Snapshot:** 2026-11-01 · **Branch:** `plan/desktop-rust-migration` · **Scope:** first vertical slice

This file is evidence, not a plan. It records what now exists, what the gates can
actually prove, and what is still open. It is updated at every merge.

---

## 1. What is implemented

| Area | State | Location |
|---|---|---|
| ADRs 0007–0016 | **Done** | `docs/adr/` |
| Rust workspace (5 crates + Tauri app) | **Done** | `rust/Cargo.toml` |
| Money in integer sen, half-away-from-zero | **Done, parity-tested** | `hragents-core/src/money.rs` |
| Business timezone (`Asia/Jakarta`) | **Done** | `hragents-core/src/time.rs` |
| Typed IDs with human short refs | **Done** | `hragents-core/src/ids.rs` |
| SHA-256 append-only audit chain | **Done, parity-tested** | `hragents-core/src/audit.rs` |
| Argon2id password + session lock/re-auth | **Done** | `hragents-core/src/{password,auth}.rs` |
| Deterministic evaluation merge + policy gate | **Done** | `hragents-core/src/hiring.rs` |
| People, contracts, documents, onboarding | **Done** | `hragents-core/src/people.rs` |
| Leave balances and decisions | **Done** | `hragents-core/src/leave.rs` |
| Payroll monthly/THR/final, BPJS, PPh 21, overtime | **Done, PPh 21 parity-tested** | `hragents-core/src/payroll.rs` |
| Approvals/Today ordering | **Done** | `hragents-core/src/approvals.rs` |
| Consent, retention, erasure, breach | **Core done; UI partial** | `hragents-core/src/compliance.rs` |
| Policy retrieval with citations | **Done (keyword fallback)** | `hragents-core/src/policy.rs` |
| Deterministic extractor + agent contracts | **Done (offline keyword extractor)** | `hragents-agents/src/lib.rs` |
| Payroll review packet (XLSX) | **Done** | `hragents-ipc/src/lib.rs` export |
| SQLite schema v1 (47 tables + 5 FTS5) | **Done** | `hragents-store/migrations/0001_init.sql` |
| Migrations, WAL, FTS5, backup + integrity check | **Done** | `hragents-store/src/lib.rs` |
| SQLCipher feature + reopen/wrong-key test | **Code done; CI job added; local Windows build blocked** | `hragents-store` feature `sqlcipher` |
| Typed application services (no Tauri dependency) | **Done** | `hragents-ipc/src/lib.rs` |
| CLI demo / verify / backup | **Done** | `hragents-cli/src/main.rs` |
| Tauri 2.12.5 shell, typed commands, SQLite state | **Done; binary launches** | `rust/apps/desktop` |
| Five-surface React UI + login/lock | **Done** | `rust/apps/desktop/ui` |
| Python parity export + golden tests | **Done (money, audit, PPh 21, scoring merge)** | `scripts/parity_export.py`, `parity/fixtures` |
| CI for Rust, UI, and fixture regeneration | **Done** | `.github/workflows/desktop.yml` |

### Evidence

```text
cargo test --workspace --exclude hragents-desktop
  hragents-agents  4 passed
  hragents-core   45 passed
  python_parity    5 passed
  hragents-store   8 passed
  hragents-ipc     8 passed (1 release benchmark ignored)
  total           70 passed

cargo clippy --workspace --exclude hragents-desktop --all-targets -- -D warnings
  Finished (no warnings)

cargo build -p hragents-desktop
  Finished (Tauri 2.12.5 binary)

hragents-cli demo ...
  login, employee, onboarding, evaluation 81.0% + gated rejection,
  leave 2 days, payroll gross Rp12.000.000 net Rp11.520.000,
  audit 16 entries, backup verified, search 1 hit

cargo test -p hragents-ipc --release payroll_1000 -- --ignored --nocapture
  payroll_1000: 1000 lines, elapsed 12.69ms (budget 2s)

payroll XLSX export test
  summary + lines sheet written, audit row payroll.exported

tauri app launch
  %LOCALAPPDATA%\com.hragents.desktop\hragents.db created
  integrity_check = ok
```

The browser preview (`npm run dev`) was exercised with Playwright across all five
surfaces: Today, Hire case file + gated rejection, People onboarding + leave,
Pay compute + password sign-off, Ask citations, Settings audit verification.

---

## 2. Gate status — honest

| Gate | Proof required | Status |
|---|---|---|
| **G0** shell + DB + login | Packaged build, encrypted DB, login/lock/unlock/re-auth, audit after restart, no listening port | **Partial.** Binary launches, DB opens, login/lock/audit code exists. SQLCipher is behind a feature with a CI job, but not locally verified (Windows Perl lacks `Locale::Maketext::Simple`); no signed installer. |
| **G1** employee/onboarding | Employee created, plan completed, audited receipt, parity fixture, Python not invoked | **Pass on the dev slice.** Covered by IPC tests and CLI demo. |
| **G2** hiring case file | CV → extraction → score → evidence → review → rejection sign-off | **Partial.** Import, offline text extraction, score, σ, evidence, gate, and rejection pass. PDF/DOCX parsing and a provider-backed (`rig`) extractor are not ported. |
| **G3** payroll | 1,000-employee run matches Python to the sen; verified tables; sign-off; immutable; export | **Partial.** Engine, tables gate, anomalies, sign-off, immutability, 1,000-line benchmark (12.7 ms), and XLSX export exist. Full BPJS/THR/final parity corpus still missing. |
| **G4** docs/compliance | Leave, document requests, retention, erasure, consent, audit export, policy chat | **Partial.** Core consent/erasure/retention and policy retrieval exist; document-request workflow, audit export UI, and full compliance UI are not wired. |
| **G5** no Python | Five journeys on packaged build, full parity green, no Python in bundle | **Not started.** Python remains the reference implementation. |
| **G6** signed installer/update/backup | Signed installer, notarized macOS, staged updater, restore drill, rollback | **Not started.** Backup/restore and integrity check exist; signing and updater do not. |

A gate is not opened by a green unit test. G0, G2, G3, and G4 remain open until the
missing evidence above exists.

---

## 3. What is deliberately still missing

1. **Provider-backed agent layer (`rig`)** — the deterministic offline extractor and
   policy-answer contract exist; prompts, structured-output providers, streaming,
   and recorded LLM fixtures do not.
2. **CV ingestion and document preview** — bytes are hashed and metadata stored, but
   no extractor or viewer yet.
3. **SQLCipher local verification** — the feature, `open_encrypted`, and the
   reopen/wrong-key test exist. The Windows GNU build failed in OpenSSL's Perl
   configure (`Locale::Maketext::Simple` missing); the Ubuntu CI job is the evidence
   path. A release build must run it before G0 is closed.
4. **Packaged installer, code signing, updater** — `cargo build` works; distribution
   does not exist yet.
5. **XLSX payroll export, payslips, 1,000-employee benchmark** — engine only.
6. **Scheduling, offers, candidate messaging, feedback PDF** — core models exist;
   workflows and UI are not ported.
7. **Growth, offboarding, document requests** — tables exist; services/UI do not.
8. **Scoring parity breadth** — the merge and population σ are parity-tested against
   Python's `aggregate_runs`; the 4-dimension rubric extraction itself is not yet.
9. **Payroll parity beyond PPh 21** — BPJS/THR/final need a Python-generated corpus.
10. **Import from the existing Postgres product** — not implemented.

---

## 4. Next ten tasks, in order

1. Add SQLCipher behind a default release feature; rekey and reopen tests.
2. Port CV extraction with `rig` 0.46 and a recorded offline provider; store raw
   output hashes. (The deterministic extractor is the fallback.)
3. Generate scoring and full payroll parity corpora from Python; make them
   shrink-only.
4. Implement document upload/preview and the document-request workflow.
5. Implement scheduling, offers, and candidate communications.
6. Add payroll XLSX export and payslip view; benchmark 1,000 lines.
7. Wire growth and offboarding services and screens.
8. Add audit export, retention sweep, and the erasure execution flow over IPC.
9. Package: NSIS/MSI, signed updater manifest, clean-VM install + restore drill.
10. Cut over: freeze corpus, delete Python from the runtime, run G5/G6.

---

## 5. How to run it now

```bash
# Rust workspace
cd rust
cargo test --workspace --exclude hragents-desktop
cargo run -p hragents-cli -- demo target/demo.db
cargo run -p hragents-cli -- verify target/demo.db
cargo build -p hragents-desktop

# UI (browser preview uses the same typed command names)
cd rust/apps/desktop/ui
npm install
npm run dev        # http://127.0.0.1:1420
npm run build
```

The packaged app opens with the first-run wizard. In browser preview, demo data is
loaded and no database is touched.
