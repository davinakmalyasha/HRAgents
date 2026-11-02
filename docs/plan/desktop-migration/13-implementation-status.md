# 13 — Implementation Status

**Snapshot:** 2026-11-02 · **Branch:** `plan/desktop-rust-migration` · **Edition:** free (unsigned, no account, no telemetry)

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
| Argon2id password + session lock/re-auth | **Done; UI polls for idle lock** | `hragents-core/src/{password,auth}.rs`, `App.tsx` |
| Deterministic evaluation merge + policy gate | **Done** | `hragents-core/src/hiring.rs` |
| People, contracts, documents, onboarding | **Done** | `hragents-core/src/people.rs` |
| Leave balances and decisions | **Done** | `hragents-core/src/leave.rs` |
| Payroll monthly/THR/final, BPJS, PPh 21, overtime | **Done, PPh 21 parity-tested** | `hragents-core/src/payroll.rs` |
| Approvals/Today ordering | **Done** | `hragents-core/src/approvals.rs` |
| Consent, retention, erasure, breach | **Done across core/store/IPC/UI** | `hragents-core/src/compliance.rs` |
| Policy retrieval with citations | **Done (keyword fallback)** | `hragents-core/src/policy.rs` |
| Deterministic extractor + agent contracts | **Done (offline keyword extractor)** | `hragents-agents/src/lib.rs` |
| Document text extraction (TXT/PDF/DOCX) | **Done, fixture-tested** | `hragents-agents/src/documents_text.rs` |
| Provider-backed extraction (`rig` 0.46) | **Done (ReplayClient tested, live test ignored)** | `hragents-agents/src/provider.rs` |
| File-based scoring (upload → parse → score) | **Done (IPC + Tauri + UI)** | `extract_and_evaluate` |
| Background scheduler (retention/offer/backup/audit/outbox) | **Done, wired in Tauri setup** | `hragents-ipc/src/scheduler.rs` |
| Reminders (overdue/stalled/expiring) + outbox sweep | **Done, scheduler + Today UI** | `hragents-core/src/reminders.rs` |
| Inbox poll (IMAP-gated explicit error) | **Done (config-gated)** | IPC `poll_replies` |
| CLI restore with verify-first/refuse-newer/snapshot/atomic swap | **Done, drill-proven** | `hragents-cli restore` |
| Pilot plan + restore-drill runbook | **Done** | `15-pilot.md`, `16-restore-drill.md` |
| Parity corpus freeze | **Done** | `parity/FROZEN.md` |
| Payroll review packet (XLSX) | **Done** | `hragents-ipc/src/lib.rs` export |
| Growth cycles, review forms, goals | **Done across core/store/IPC/UI** | `hragents-core/src/growth.rs` |
| Offboarding checklist + final-pay gate | **Done across core/store/IPC/UI** | `hragents-core/src/offboarding.rs` |
| Document requests + vault upload/preview/verify | **Done** | `hragents-core/src/documents.rs`, `screens/Documents.tsx` |
| Audit export (JSON) | **Done** | `export_audit`, Settings screen |
| SQLite schema v2 (47 tables, 5 FTS5, 37 named indexes) | **Done; v1 databases upgrade in place** | `hragents-store/migrations/{0001_init,0002_indexes}.sql` |
| N+1 removal on Today/reminders | **Done** | `list_onboarding_plans` (two queries, not one per employee) |
| WAL, FTS5, backup + integrity check | **Done** | `hragents-store/src/lib.rs` |
| SQLCipher database encryption | **Enabled in the desktop build** | `Store::open_encrypted`, `apps/desktop` enables the feature |
| Per-install key | **32 random bytes; DPAPI-wrapped on Windows, mode 0600 elsewhere** | `hragents-store/src/keyfile.rs` |
| Recovery-key export | **Reauth + password gated, audited, no key in audit payload** | `AppService::recovery_key` |
| Pre-login recovery screen | **Accepts the 64-hex key, verifies the DB + operator, rewraps, audits** | `screens/Recovery.tsx`, `recover_encrypted_database` |
| Key rewrap / recovery | **Rewrap the same key for the current OS user; CLI `rewrap` for another machine** | `AppService::rewrap_install_key`, CLI |
| Full backup set | **ZIP: DB + documents + key + SHA-256 manifest; restore verifies every hash** | `hragents-ipc/src/backup_set.rs` |
| Audited key rotation | **Rekey DB, re-encrypt documents, sealed journal, resumable** | `hragents-store/src/rotation.rs` |
| Plaintext → encrypted migration | **In place, verified, plaintext copy removed** | `Store::encrypt_plaintext_in_place` |
| Encrypted uploaded documents | **ChaCha20-Poly1305; legacy files migrate on open** | `crates/hragents-ipc` document vault |
| Encrypted backups | **SQLCipher export; wrong key fails closed** | `Store::backup_to`, `Store::backup_to_key` |
| CLI access to encrypted DBs | **`--key` / `--key-file`; explicit SQLCipher feature** | `hragents-cli` |
| Typed application services (no Tauri dependency) | **Done** | `hragents-ipc/src/lib.rs` |
| CLI demo / verify / backup / restore | **Done** | `hragents-cli/src/main.rs` |
| Tauri 2.12 shell, typed commands, SQLite state | **Done; binary launches** | `rust/apps/desktop` |
| Single-instance guard | **Done** | `tauri-plugin-single-instance` focuses the running window |
| Strict CSP split (production vs dev) | **Done** | `tauri.conf.json` `security.csp` / `devCsp` |
| NSIS installer (free edition: unsigned, per-user, no admin) | **Done locally: 7.20 MiB with SQLCipher + recovery/rotation UI** | `bundle/nsis/HRAgents_0.1.0_x64-setup.exe` |
| Auto-update | **Intentionally absent.** No paid account, no hosted server, no phone-home. | Settings → Updates explains it |
| Five-surface React UI + login/lock | **Done; screens code-split** | `rust/apps/desktop/ui` |
| UI refinement pass | **Done: focus trap/restore, skip link, reduced motion, scoped table headers, associated labels, keyboard shortcuts, neutral count/status colour, loading skeleton** | `App.tsx`, `components/ui.tsx`, `styles.css`, `theme.css` |
| Python parity export + golden tests | **Done (money, audit, PPh 21, scoring merge)** | `scripts/parity_export.py`, `parity/fixtures` |
| CI for Rust, UI, and fixture regeneration | **Done** | `.github/workflows/desktop.yml` |

### Evidence

```text
cargo test --workspace --exclude hragents-desktop
  hragents-agents  16 passed, 1 ignored (live provider)
  hragents-core    67 passed
  payroll_parity    4 passed
  python_parity     5 passed
  hragents-ipc     24 passed, 1 ignored (release benchmark)
  hragents-store   18 passed (includes key-file and document-crypto tests)
  total           134 passed, 2 ignored

cargo clippy --workspace --exclude hragents-desktop --all-targets -- -D warnings
  Finished (no warnings)

cargo test -p hragents-store --features sqlcipher  (Windows GNU, Strawberry-perl transplant)
  24 passed, including encrypted reopen, wrong-key rejection, raw 256-bit key,
  plaintext-to-encrypted migration, encrypted backup round-trip, key rewrap,
  full rotation, and both crash-resume scenarios

cargo test -p hragents-ipc --features sqlcipher
  27 passed, 1 ignored; the encryption/recovery tests cover:
  plaintext DB + document -> key file -> encrypted reopen -> login ->
  encrypted document read -> encrypted backup -> reopen backup

NSIS (free edition, unsigned, per-user, SQLCipher)
  HRAgents_0.1.0_x64-setup.exe, 7,548,314 bytes (7.20 MiB)
  SHA-256 c22e1541424a6f675ddbbe82e8c4f93f77fe7fc0170ac1fe8ca97d0d6139bb93
  built binary launches; a second launch exits 0 while the first keeps running

live upgrade of the real local database (not a fixture):
  before: header "SQLite format 3" magic, 679,936 bytes
  after:  encrypted header, hragents.key = 262-byte DPAPI blob, 684,032 bytes
  CLI verify --key-file hragents.key -> encrypted: yes, integrity: ok
  wrong key -> "file is not a database" (fail closed)
  encrypted backup 684,032 bytes (not plaintext) -> restore -> verify encrypted: yes
  tampered document ciphertext -> read rejected

recovery and full-set CLI drill:
  recovery key export: wrong password rejected; correct password returns 64-hex; audited
  pre-login recovery: key file deleted -> recover_with_key -> login + key rewrapped +
  "security.recovered" audit entry; wrong key leaves the key file absent
  key rotation: old key fails, new key opens, document re-encrypted, audited
  interrupted rotation: DB rekeyed + documents old + key old -> resume finishes;
  corrupted rekey -> pre-rotation backup restored and rekeyed
  packaged app with hragents.key temporarily removed: UI Automation reads
  "Recover this installation", the 64-hex hint, username/password fields, and
  "Recover and sign in"; the DB still verifies encrypted after the key returns
  rewrap: same key, new OS-protected hragents.key; database still verifies encrypted: yes
  backup-set: 684,968 bytes, members manifest.json + hragents.db + hragents.key
  restore-set: 0 documents, 0 audit entries, verify encrypted: yes
  restore-set with wrong key: exit 1, "file is not a database"

uv run python scripts/check.py (Python oracle gate, unchanged runtime)
  2234 passed, 5 skipped, coverage 92.41%, invariants ok

cargo test -p hragents-ipc --release payroll_1000 -- --ignored --nocapture
  1000 lines, ~12.7 ms (budget 2 s)

cargo run -p hragents-cli -- verify <copy of a real v1 database>
  ok: 0 audit entries, head (empty)
  integrity: ok
  PRAGMA user_version: 1 -> 2
  schema_migrations: (1,), (2,)
  index objects: 71 -> 88 (37 named; the rest are implicit PK/UNIQUE indexes)
  missing legacy columns added: growth_assignments.reviewer_email/created_at/sent_at/submitted_at,
                                offboarding_plans.final_pay_run_id

UI build (initial bundle, five screens lazy-loaded):
  index  330.44 kB / 99.26 kB gzip
  Hire    35.34 kB, People 27.57 kB, Pay 14.57 kB, Settings 13.24 kB, Ask 7.09 kB
  (before split: single 436.50 kB / 119.89 kB gzip initial)

Playwright, 1024x700 and 1440x900 browser preview:
  Today, Hire, People, Pay, Ask, Settings rendered; keyboard ? opens the grouped
  shortcut dialog; Esc closes it and restores focus; g-t/g-h/g-p/g-y/g-a/g-s
  navigate; skip link is first in tab order; reduced-motion and focus rings present.
```

The browser preview (`npm run dev`) uses the same typed command names as Tauri and
the same gates; it is a review surface, not a second implementation.

---

## 2. Gate status — honest

| Gate | Proof required | Status |
|---|---|---|
| **G0** shell + DB + login | Packaged build, encrypted DB, login/lock/unlock/re-auth, audit after restart, no listening port | **Pass on the dev slice.** Shell, per-user install, login/lock/re-auth, audit-after-restart, and no-listening-port are proven. The app opens SQLCipher with a DPAPI-protected per-install key, converts a legacy plaintext DB in place, and stores documents and backups encrypted; a wrong key fails closed. |
| **G1** employee/onboarding | Employee created, plan completed, audited receipt, parity fixture, Python not invoked | **Pass on the dev slice.** Covered by IPC tests and CLI demo. |
| **G2** hiring case file | CV → extraction → score → evidence → review → rejection sign-off | **Pass on the dev slice.** Import, offline text extraction (TXT/PDF/DOCX), score, σ, evidence, gate, rejection, scheduling, offers, messaging, and candidate-safe feedback pass core/store/IPC/Tauri/UI tests. A live provider key is optional and untested. |
| **G3** payroll | 1,000-employee run matches Python to the sen; verified tables; sign-off; immutable; export | **Partial.** Engine, tables gate, anomalies, sign-off, immutability, 1,000-line benchmark, and XLSX export exist. Full BPJS/THR/final parity corpus and a payslip view are still missing. |
| **G4** docs/compliance | Leave, document requests, retention, erasure, consent, audit export, policy chat | **Pass on the dev slice.** Retention policies/holds/sweep, erasure request→approve→execute (reauth gates, holds block, audit survives), breach report→contain→notify→close, consent grant/withdraw, audit export, and policy retrieval pass core/store/IPC/Tauri/UI tests. |
| **G5** no Python | Five journeys on packaged build, full parity green, no Python in bundle | **Not started by design.** The migration plan forbids removing Python until the first release cut; the free edition changes distribution, not the parity contract. |
| **G6** installable free build + recovery | Per-user installer, backup/restore drill, rollback, no paid dependency | **Pass for the free edition.** NSIS installs per-user without admin, data survives uninstall, backup/restore drill is green, audit exports, and nothing requires a certificate, paid account, hosted update server, or telemetry. Commercial signing/notarization is a future paid-distribution decision, not a gate. Pilot remains a human step. |

**Threat model.** Encryption protects a stolen disk, a copied database, or a
backup without its key. It does not defend a process already running as the
logged-in Windows user: DPAPI will unwrap the key for that user. OS login and
full-disk encryption still matter, and the key file must be backed up separately.

A gate is not opened by a green unit test. G3's parity breadth, G5, and the pilot
remain open until the missing evidence exists.

---

## 3. What is deliberately still missing

1. **Provider live key + streaming** — the `rig` adapter, recorded replay fixtures,
   and the ignored live test exist; no production key is configured and there is
   no streaming UI. The offline extractor stays the default.
2. **Parity breadth** — the merge and population σ are parity-tested; the
   4-dimension rubric extraction itself is not. BPJS/THR/final payroll need a
   Python-generated corpus before the sen-level claim covers them.
3. **Payslip view** — payroll exports a review packet; there is no per-employee
   payslip screen yet.
4. **Python removal** — deferred to the release cut by the migration plan.
5. **Import from the existing Postgres product** — not implemented.
6. **Paid distribution track (optional)** — Authenticode/Apple notarization and a
   signed auto-update feed are out of scope for this free edition.
7. **Pilot** — needs real companies and a named human reviewer.

---

## 4. Next tasks, in order

1. Generate the full BPJS/THR/final payroll parity corpus and add a payslip view.
2. Add extraction-level scoring parity (4 dimensions) against the Python oracle.
3. Exercise the provider adapter with a recorded replay in CI; keep the live test ignored.
4. Profile the packaged build on a 1,000-employee database; check Today/reminders
   query counts stay constant after the index migration.
5. Run the pilot entry checklist in `15-pilot.md`.
6. At the release cut: freeze the corpus, remove Python from the runtime, and run G5.

---

## 5. Replacement log — evaluated, not blindly swapped

| Candidate | Decision | Why |
|---|---|---|
| `chrono` → `jiff` | **Keep chrono for now** | Date/time semantics are already isolated in `BusinessDate`/`UtcInstant`; jiff's better DST model only pays off if raw `chrono` types leak out. Revisit at the release cut. |
| Base64 document IPC → raw `tauri::ipc::Response` | **Planned** | Base64 adds ~33% payload and an `atob` copy. The binary path needs blob-URL lifecycle work in the vault; document previews are small today, so it is not a release blocker. |
| Custom DOCX extractor → `docx-rs` | **Keep custom** | Only text is needed; the current zip + XML walk is fixture-tested and avoids a large dependency with a different document model. |
| `react-router` → none | **Removed** | The app switches five surfaces in local state; the dependency was unused. |
| `tauri-specta` | **Planned** | Generating TS types from the Rust command surface removes hand-written drift, but the command surface must freeze first. |
| Tailwind → plain CSS | **Keep Tailwind** | `theme.css` is the single token source; Tailwind supplies preflight only. Removing it would change resets across every screen for no runtime gain. |
| `rusqlite` → `sqlx` | **Keep rusqlite** | One synchronous connection is the correct model for a one-window local app; SQLx's async pool buys nothing here. |
| Zustand / i18next | **Not adopted** | TanStack Query + local state covers one window; the cockpit is English-only. |
| `aes-gcm` → `chacha20poly1305` | **Chose ChaCha20-Poly1305** | Constant-time in software on every target; no AES-NI assumption for document encryption. |
| `keyring` crate → Windows DPAPI | **Chose DPAPI directly** | Zero extra services, no DBus/Secret Service dependency; the key never leaves the OS user context. |

---

## 6. How to run it now

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
