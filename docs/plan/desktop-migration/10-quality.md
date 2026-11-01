# 10 — Quality, Parity, and Release Evidence

**Status:** draft for implementation · **Rule:** a gate is evidence, not a demo.

Quality proves two things: the Rust core makes **the same decisions** as Python, and the app is **safe to operate** on one machine and one database file.

## 1. Test pyramid

| Layer | Tooling | Target | Runs |
|---|---|---|---|
| Rust unit | `cargo nextest` | ~1,600 tests | Every PR, <60 s |
| Rust integration | nextest + temp SQLite | ~250 tests | Every PR, <6 min |
| Golden/parity | `hragents-parity` vs Python oracle | ~1,060 cases | Every PR, <20 min |
| Property | `proptest` | 30 properties × 1,000 cases | Nightly |
| Fuzz | `cargo-fuzz`, 6 targets | 1 h each | Nightly |
| SQLite migration | Fixture DBs per schema | Prior schemas | Every PR, <4 min |
| IPC contract | `tauri-specta` export + schema diff | Every command/event | Every PR, <1 min |
| Frontend unit | Vitest + Testing Library | ~350 tests | Every PR, <2 min |
| E2E | Playwright for UI; WebdriverIO + tauri-driver for the packaged app | 30 journeys | Nightly + release |
| Visual | Playwright screenshots, light/dark | ~80 screens | Every PR, <10 min |
| Accessibility | axe-core + keyboard | Every route, 0 serious/critical | Every PR |
| Performance | Criterion + startup | 16 budgets | Weekly |
| Security | `cargo deny`, `cargo audit`, `npm audit`, secret scan | Zero high/critical | Daily + release |

**Test rules.** Negative tests come first for approvals, gates, erasure, payroll corrections, and overrides. No network or real LLM; use the offline `test` provider. Dates anchor to `business_today()` in `Asia/Jakarta`. Tauri commands are tested through the same typed service the UI calls, not a mock HTTP layer.

## 2. Parity harness

The Python implementation is the oracle until Gate 5. It is tagged `oracle-0.19.0`, dependencies are frozen, and fixtures are generated from a clean checkout — never handwritten from Rust behaviour.

**Pipeline:**

1. `scripts/parity_export.py` loads seed inputs and writes canonical JSON: UTF-8, sorted keys, integer minor units, ISO-8601 UTC timestamps plus business date, fixed seeds.
2. Each case stores input, expected output, audit hash, Python version, and a SHA-256.
3. `hragents-parity` replays the identical case and emits the same canonical form.
4. Diff is exact for money, enums, booleans, ordering, hashes, and deterministic IDs; floats compare at `1e-9`, and any difference that changes a gate fails. Known Python defects live in `parity/divergences.toml` (shrink-only); a `base: spec` case needs a written rule and two approvals. Everything else blocks CI.
5. After Gate 5 the expected outputs are frozen and shipped as test data; new cases require two reviewers.

| Suite | Cases | What it pins |
|---|---|---|
| Scoring | 500 | Eight job families, EN/ID, boundary evidence, σ over k runs, name-swap invariance |
| Policy | 200 | Auto-schedule floor, rejection sign-off, approval routing, override reasons |
| Payroll | 60 scenarios | THR, PTKP, TER, BPJS caps, overtime, absence, minimum wage, 1,000 lines, negative net |
| Audit | 100 sequences | Append, verify, tamper at every position, truncation, restart |
| Documents | 100 | PDF/DOCX parsing, redaction, corrupt and oversized files |
| AI extraction | 100 | Schema fields, missing data, injection strings, invisible characters |

**Corpus governance.** `parity/manifest.json` lists every case and hash. Changing an expected value requires a written reason and two approvals: core owner and quality. Never regenerate a Python-based golden from Rust; a `base: spec` case is authored from the corrected rule.

## 3. Invariants, property tests, fuzzing

**Payroll invariants (exact, integer sen = 1/100 IDR):**

1. `net = gross − employee_deductions`; employer contributions never reduce net.
2. `gross = base + allowances + overtime + prorated THR`.
3. Run totals equal the sum of lines, to the sen.
4. Every statutory rate comes from an operator table with `verified = true`; no hardcoded rate.
5. Rounding is `ROUND_HALF_UP`, applied once per line component; no binary float in money.
6. A computed run is immutable; a correction supersedes it with a reason and a new run.
7. Period boundaries and payslip dates use `Asia/Jakarta`; no UTC date drift.
8. Export totals reconcile with the run; payroll remains prepare/verify/export, never payment.

**Audit invariants:** contiguous `seq` per company; `prev_hash` equals the prior `entry_hash`; genesis is fixed; `entry_hash` recomputes from canonical content; append-only is enforced by trigger and service; verify runs after every write and on restart; every approval, override, export, restore, and erasure names a human actor. Tamper at any row must fail verification at that row.

**Property tests:** money quantisation is idempotent and addition is commutative; the payroll identity holds for generated inputs; THR proration is monotonic in service months; a random audit chain verifies and any single-byte mutation is detected; scores stay in `[0,1]` with evidence for every non-zero dimension; the same command key returns the same result.

**Fuzz targets:** PDF, DOCX, XLSX/CSV import, policy JSON, IPC payloads, and LLM structured output. Acceptance: no panic, unbounded allocation, path traversal, or write outside app data.

## 4. Performance budgets

On 02's reference machine, p95 over 100 runs. A >10% regression fails CI.

| Metric | Budget |
|---|---|
| Cold start to interactive | ≤1.5 s |
| Warm start | ≤500 ms |
| First paint after window | ≤500 ms |
| IPC read p95 | ≤20 ms |
| IPC write p95 | ≤50 ms |
| Candidate list, 10k rows | ≤100 ms |
| Case file open (candidate + documents) | ≤150 ms |
| SQLite point read | ≤2 ms |
| SQLite list, 100 rows | ≤20 ms |
| FTS over 10k rows | ≤20 ms |
| Dashboard counts (5 aggregates) | ≤5 ms |
| Payroll compute, 1,000 employees | ≤2 s |
| Payroll export, 1,000 employees | ≤10 s |
| Audit verification, 100k entries | ≤1 s |
| Idle memory | ≤150 MB |
| Installer | ≤35 MB |

Benchmarks live in `hragents-parity` benches and `web/e2e/perf/`; results are committed as JSON and charted weekly.

## 5. CI and release engineering

| Job | OS | Blocking |
|---|---|---|
| `fmt`, `clippy -D warnings`, unit, integration | Windows, macOS, Ubuntu | Yes |
| Frontend lint, format, typecheck, Vitest, build | Ubuntu | Yes |
| IPC schema diff | Ubuntu | Yes |
| SQLite migration + parity | Windows, Ubuntu | Yes |
| Packaged E2E, five journeys | Windows, macOS | Yes on release, nightly otherwise |
| Visual + accessibility | Ubuntu | Yes |
| `cargo deny`, `cargo audit`, `npm audit`, secret scan | Ubuntu | Yes |
| SBOM (CycloneDX), checksums, provenance | Release tag | Yes |
| Signed Windows build, notarized macOS build, updater artifacts | Release tag | Yes |
| Criterion + startup benchmarks | Windows reference runner | Weekly trend; blocks release |

PR feedback target: under 25 minutes; branch protection requires the full matrix. Release artifacts are signed, checksummed, and accompanied by `latest.json`; the updater verifies signatures before applying.

**Release checklist:** version and changelog; parity green on the release commit; upgrade from N−2 and N−1; clean-VM install; upgrade; rollback; backup/restore; audit verification; keyboard and screen-reader pass; EN/ID strings; all performance budgets; Windows signature and macOS notarization; staged updater 5% → 25% → 100%; crash reporting opt-in; docs and demo company; pilot sign-off; SBOM attached.

**Crash reporting:** panic hook writes a local report (version, OS, command, redacted stack); upload is opt-in, rate-limited, and never includes database rows, document text, or credentials. Symbols are archived per release.

**Backup/restore:** encrypted backup every six hours and at first launch after the local date changes, using SQLite's online backup API; retention 14 daily + 3 monthly; `PRAGMA integrity_check` before and after. A restore drill runs every release and after every schema migration: restore to a temp path, verify table counts and the full audit chain, open the app, run one journey.

**Migration and rollback:** back up before migrating; run migrations in one transaction with `user_version`; test against fixtures for every released schema. There are no down-migrations: rollback is restoring the pre-update backup and reinstalling the previous signed build, rehearsed before Gate 6.

## 6. Definition of done by phase

| Phase | Done means |
|---|---|
| 0 | ADRs accepted; oracle tagged and hashed; corpus plan and budgets approved; CI skeleton green |
| 1 | G0 and G1; packaged build; login/lock; audit verifies after restart; first fixtures |
| 2 | G2–G4; payroll parity exact; rate tables verified; no LLM in any decision path |
| 3 | G5; five journeys; 0 serious/critical a11y issues; visual baselines; Python absent from runtime |
| 4 | All budgets; fuzz clean 7 days; security review closed; restore and rollback drills pass |
| 5 | G6; signed installer and updater; pilot acceptance; Python source deleted; support runbook |
