# 03 — Rust backend

**Status:** draft · **Date:** 2026-11-01 · **Depends on:** [`02-architecture.md`](02-architecture.md), [`04-sqlite-data.md`](04-sqlite-data.md)

One Rust process per install: no Python, no Postgres, no Redis, no localhost HTTP. This
document fixes the workspace, boundaries, numeric and time types, AI layer, and the
parity gates that decide when Python may be deleted.

---

## 1. Strategy: Python is the oracle, never the runtime

Rust lives in a new `rust/` workspace. Python keeps shipping and keeps its current ~2,200-test gate
(`scripts/check.py`) green until Gate 5 ([`09-sequence.md`](09-sequence.md)), but it never
enters the installer: no sidecar, no embedded interpreter, offline fixtures only. Porting
is by vertical slice — one IPC command plus fixtures, then flip the UI.

```
parity/  SCHEMA_VERSION · cases/<module>/<case>.json · golden/<module>/<case>.json
         divergences.toml · llm/<agent>/<case>.jsonl · manifest.json
```

Each case carries its input, a frozen clock, fixed UUIDs, and `base: "python" | "spec"`.
`scripts/parity_export.py` imports the Python services directly (no HTTP, no DB) and writes
the goldens; `scripts/parity_verify.py` fails if the oracle moved, so regeneration is a
reviewed diff. `hragents-parity` replays them through the real Rust core with `insta` and
prints the JSON pointer of the first mismatch. `divergences.toml` covers cases where Python
is wrong (§6) and fails the build if it grows. Clock, ids, and randomness are injected
everywhere: a core test reading `SystemTime::now()` or `rand` fails §2.

---

## 2. Workspace and crate boundaries

```
rust/  Cargo.toml (resolver 3, edition 2024) · rust-toolchain.toml (1.99.1)
       crates/hragents-{core,store,app,agents,import,ipc,api,parity} · apps/desktop
```

| Crate | Contents | Dependencies |
|---|---|---|
| `hragents-core` | Models, money, time, ids, errors, scoring, policy, priority, payroll math, audit hashing, approvals, rubrics. No I/O | `serde`, `rust_decimal`, `chrono`, `uuid`, `thiserror`, `schemars`, `sha2`, `libm` |
| `hragents-store` | Migrations, repositories, FTS5, audit sink, backup. No business rules | `hragents-core`, `rusqlite` |
| `hragents-app` | Use cases, transactions, session gate, audit orchestration, exports. No Tauri macros | `hragents-core`, `hragents-store`, `hragents-import`, `hragents-agents` traits |
| `hragents-agents` | `rig` providers, prompts, tool loop, streaming, replay | `hragents-core` |
| `hragents-import` | CSV/XLSX/PDF/ICS/IMAP → core DTOs, reviewed before write | `hragents-core`, `hragents-store` |
| `hragents-ipc` | Tauri commands, `tauri-specta`, errors, pagination, channels | `hragents-app` |
| `hragents-api` | Optional Axum, feature `server`, off by default | `hragents-app` |
| `hragents-parity` | Fixture replay, boundary test, benches (dev-only) | all |

Acyclic: `hragents-core ← hragents-store ← hragents-app ← {hragents-ipc, hragents-api}`,
`hragents-core ← hragents-store ← hragents-import ← hragents-app`, and
`hragents-core ← hragents-agents ← hragents-app`. `hragents-agents` cannot see
`hragents-app`, so an agent has no compile-time route to a mutating use case.
`hragents-parity::boundaries` parses each `Cargo.toml` and asserts the edge set.

---

## 3. Domain module map and port order

| # | Module and Python reference | Why this position |
|---|---|---|
| 0 | Foundations: `models/common.py`, `money.py`, `errors.py` | Imported everywhere |
| 1 | Audit: `services/audit.py`, `models/audit.py` | Every write appends |
| 2 | Auth/session/gate: `identity.py`, `api/routers/session.py` | Gate must be a type before writes |
| 3 | Approvals: `services/approvals.py` | Four modules create them |
| 4 | People: `services/{people,employees,contracts}.py` | The foreign key of everything |
| 5 | Hiring: `services/{scoring,policy,priority,rubrics,pipeline}.py` | Pure; proves the harness |
| 6 | Onboarding: `services/onboarding.py` | Small; needs people + approvals |
| 7 | Leave: `services/{leave,attendance,calendar}.py` | Feeds payroll proration |
| 8 | Payroll: `services/payroll.py`, `models/{payroll,compensation}.py` | Highest risk; math starts at #5 |
| 9 | Growth: `services/growth.py` | Independent |
| 10 | Offboarding: `services/offboarding.py` | Needs approvals + `FINAL` |
| 11 | Compliance: `services/{compliance,retention,documents}.py` | Erasure touches everything |
| 12 | Search: new FTS5 | Indexes everything |
| 13 | Chat: `services/{chat,front_door}.py` | Tools call everything |

Order is dependency-first and risk-first: 1–3 are cross-cutting and cost every call site
if retrofitted; 5 is pure and validates parity before the expensive domains; 8 gets the
most schedule; 11–13 are consumers. Modules live in `hragents_core::<name>`. The ten workspaces in
`src/hr_agents/workspaces.py` become UI surfaces (five, per
[`07-ui-ux.md`](07-ui-ux.md)), not security boundaries: no `rbac.rs`, no `tenancy.rs`, no
`Permission` enum.

---

## 4. Data types

| Concept | Rule and parity |
|---|---|
| Money | `struct Money(i64)` in **sen**, checked arithmetic, never `f64`; Python's 2dp `Decimal` is exact in i64 sen |
| Ratios | `rust_decimal::Decimal` parsed from the JSON number's **text**, matching `Decimal(str(percent))` (`money.py:138`); never `as f64` |
| Rounding | `MidpointAwayFromZero`, one quantise per statutory boundary, matching `ROUND_HALF_UP` |
| Business date | `BusinessDate(NaiveDate)` only from `business_today(now)` in `Asia/Jakarta` (`models/common.py:65`); never `Local::now()` |
| Instant | `UtcInstant(DateTime<Utc>)`; INTEGER unix ms, audit stores isoformat TEXT with `+00:00`, never `Z` |
| Ids | `Uuid` newtype per aggregate; v7 for new rows, v4 still parses; UUID strings in fixtures |
| Actor | `Actor { id, kind: Human \| Agent \| System }`; `Human` only from `&Session`, `AgentActor` is a distinct type |
| Errors | `thiserror` enum + `DomainError { code, message, details }`; `DomainCode` copied from `errors.py`, 1:1 over IPC |
| Serde / schemas | `camelCase`, `deny_unknown_fields` (matches `StrictModel`); `#[derive(JsonSchema)]` serves IPC and tool schemas |
| Concurrency | `version: u64`; mismatch → `DomainCode::StaleWrite` (`db/mapping.py`) |

Reject `|amount| > 10^15` rupiah at parse: `rust_decimal`'s 96-bit coefficient and
Python's `prec=40` context cover every intermediate, and away-from-zero rounding makes
them agree.

---

## 5. Deterministic core

- **Scorer** (`services/scoring.py`): four axes, weights 0.40/0.30/0.20/0.10, `s_tech`
  weighted mean, every dimension evidence-backed or neutral.
- **Policy** (`services/policy.py`, `docs/archive/python-server/architecture/hitl-bounds.md` §4): first match
  wins — consent → flags → slots → evidence → auto band (`s ≥ 0.75 ∧ σ ≤ 0.05`) →
  soft-rejection → reject.
- **Priority** (`services/priority.py`): `P = α·S̄ + β·e^(−λΔt) + γ·A − δ·R`, clamped
  `[0,1]`, `round(6)`, stable ties.
- **k-run σ** (`models/evaluation.py::aggregate_runs`): `k = scoring_runs` floored at 2,
  **population** stddev of per-run weighted scores, `round(6)`.
- **Evidence and rubrics**: refs deduplicated and ordered, never backfilled; an immutable
  rubric snapshot (version + thresholds) is stored on each evaluation.

`e^(−λΔt)` uses `libm::exp`, not `f64::exp`, so x86_64 and aarch64 agree bit-for-bit.
Goldens plus `proptest`: score ∈ [0,1], σ = 0 for identical runs, permutation-stable
ranking for equal inputs.

---

## 6. Payroll

Order: wage = base + fixed allowances → absence proration as an **exact ratio**, never
quantised (`payroll.py:918`) → overtime from the verified `overtime_premium` table
(per-day tiers, no default) → BPJS per `bpjs_*` table with `wage_cap` applied **before**
the percentage → PPh 21 PTKP lookup then TER → deductions (loans, other) →
`net = gross − deductions`, `employer_cost = gross + employer contributions`. Tables
resolve once per run, not per line.

Invariants (runtime check + `proptest`): no negative money; gross equals the sum of its
components; net equals gross minus deductions; `absence_days == working_days` pays exactly
zero; recomputation is byte-identical; line sums equal run totals.

**Python's two known gaps — Rust fixes them, it does not copy them**

| Gap | Python today | Rust target |
|---|---|---|
| THR | BPJS on a termination payout is unmodelled; an ERROR anomaly blocks sign-off (`payroll.py:783-826`) | `thr_bpjs_mode` (`none` \| `prorated_monthly`) from a verified row, recorded on the run: no silent withholding, no permanent block |
| FINAL | `FINAL` exists (`models/payroll.py:41`) but `compute` routes it to `_compute_line` (`payroll.py:653`), emitting a monthly payslip labelled "final" | Prorated final-month wage + unused-leave payout + severance per a new `severance` ladder + THR accrued for the final year + expenses, less final-month BPJS, TER, and loan balance |

Both are `base: "spec"` fixtures: a human-reviewed Rust golden plus a divergence entry. An
uncovered ladder is a hard error naming the missing key, never an invented figure. Payroll
ends at export (`rust_xlsxwriter`, CSV, PDF); no payment-execution code exists.

---

## 7. Audit chain

- Canonical bytes: sorted keys, compact separators, `ensure_ascii`, shortest round-trip
  float repr, `2026-11-01T09:00:00.123456+00:00`. Python's `canonical_json`
  (`models/common.py:152`) is the definition; `serde_json` alone is not byte-compatible,
  so `hragents_core::audit::canonical` is hand-written and tested on non-ASCII, floats, nested maps,
  and nulls.
- `entry_hash = SHA-256(canonical(prev_hash, actor, action, subject_type, subject_id,
  payload, created_at))`, `sha2` only.
- Append-only twice: `BEFORE UPDATE`/`BEFORE DELETE` triggers that `RAISE(ABORT)`, and a
  single writer connection. Verification streams by `seq` with a cursor, so 500k entries
  verify without loading.
- Export writes JSONL plus `manifest.json` (rows, head hash, format version) and
  re-verifies before closing the handle. Cross-check: 500 Python entries with Indonesian
  text and a float payload must hash identically in Rust.

---

## 8. Auth, session, and the named-human gate

- Argon2id v19, m = 64 MiB, t = 3, p = 1, 16-byte salt, 32-byte output, constant-time
  verify; the database key lives in the OS keychain.
- One role: `enum Role { HrOperator }` — named so authorization has a subject, not so a
  matrix can grow.
- `Session { operator_id, opened_at, last_active_at, reauthenticated_at, role }`. Idle lock
  at **15 min**; re-auth within **5 min** for payroll sign-off, erasure, rejection override,
  rate-table verification, and approval decisions.
- The gate is a constructor: `Actor::human(&Session)` is the only path to
  `ActorKind::Human`, every mutating use case takes `&Session`, and `agent:`/`system`
  prefixes are rejected at deserialization — closing the bug class in `identity.py`.
- No `tenant_id`, no RLS: one company per file, recorded in `db_meta.company_id` for backup
  identity only. IPC commands take `&Session` via the extractor; only `auth_*` and
  `app_info` are exempt, and a test asserts that list.

---

## 9. AI layer

- **Providers and output:** `rig` 0.46 (OpenAI, Anthropic, Gemini, Ollama, OpenRouter,
  Groq); fallback is OpenAI-compatible `/chat/completions` over `reqwest`. Structured
  output is a `#[derive(JsonSchema)]` DTO through `Extractor` plus a Rust validator;
  endpoints without native schemas fall back to prompted JSON through the same validator.
- **Tool loop:** `rig::tool::Tool` over a read-only registry; `request_approval` creates an
  approval. Destructive calls carry an argument digest — same arguments as previewed, at
  most one execution — porting the three properties of `src/hr_agents/tools/gating.py`.
- **Streaming and retries:** `StreamingCompletion` → `ipc::Channel<ChatDelta>`; 3 attempts,
  250 ms base, full jitter, only 429/5xx/timeout, with a per-provider circuit breaker.
- **Config and prompts:** `provider_settings` table, key in the keychain, offline `test`
  provider as the zero-config default. Prompts live in
  `rust/crates/hragents-agents/prompts/`, mirroring
  `src/hr_agents/skills/{platform,recruiting}/`, loaded with `include_str!`; a
  whitespace-normalised diff test makes prompt drift a failing test.

Tests never touch the network: `ReplayProvider` replays `parity/llm/*.jsonl` by request
hash, and the `test` provider id stays reserved. Every capability has a Rust fallback; no
path returns to Python.

---

## 10. API surface

- **Naming:** `domain_verb_noun` — `hiring_list_queue`, `payroll_compute_run`,
  `leave_approve_request`, `audit_verify_chain`, `search_query`.
- **Bindings:** `collect_commands!` → `web/src/lib/bindings.gen.ts`, committed; CI fails on
  a stale diff, as `scripts/export_openapi.py` does today.
- **Errors and paging:** `Result<T, IpcError>` with `{ code: DomainCode, message, details?,
  retryable }`; cursor over `(updated_at, id)` returning `{ items, next_cursor, total }`,
  default 50, max 200. Large reads stream over `ipc::Channel<T>` — payroll lines, audit
  export, search — never a 20 MB JSON value.
- **Search:** FTS5 `unicode61`; Indonesian stemming is out of scope for v1.
- **Server edition:** `api` behind `--features server`, same use cases on `/v1/*`, diffable
  against `tests/test_route_inventory.py`; CI asserts `cargo tree --no-default-features` has
  no `axum`.

---

## 11. Performance

| Budget | Target | Measured by |
|---|---|---|
| Cold start | < 1.5 s | `apps/desktop/tests/startup.rs` + release E2E |
| IPC read p95 (10k employees) | < 20 ms | `benches/ipc_reads.rs` + one WebDriver round trip |
| Payroll, 1,000 employees | < 2 s | `benches/payroll_1k.rs`, `criterion`, release |
| Idle RAM (RSS) | < 150 MB | `sysinfo` sample at 60 s idle |
| Installer | < 35 MB | CI artifact gate; WebView2 runtime excluded |

Profile: `lto = "fat"`, `codegen-units = 1`, `panic = "abort"`, `strip = "symbols"`,
`opt-level = 3`. Abort means a stray `unwrap` kills the app, so libraries carry
`#![deny(clippy::unwrap_used, clippy::expect_used)]`. SQLite is **`rusqlite` 0.41 (bundled
3.54.1)** behind `deadpool-sqlite` (4 connections, 1 writer); SQLx 0.9 only if compile-time
checking ever outweighs its background-thread shim. Pragmas: WAL, `synchronous=NORMAL`,
`foreign_keys=ON`, `busy_timeout=5000`, `temp_store=MEMORY`, 256 MB mmap. `tokio` owns
network and jobs; SQLite calls run in `spawn_blocking`, use cases stay synchronous per
`docs/adr/0005-sync-domain-async-edge.md`. Zero-copy where it pays:
`serde_json::from_slice`, borrowed `&str` DTOs, `bytes::Bytes`, `tauri::ipc::Response` for
binary — no base64, no needless JSON round-trip.

---

## 12. Dependency matrix (latest stable, 2026-11-01)

| Crate | Version | Use |
|---|---|---|
| Rust | 1.99.1 | Toolchain, edition 2024 |
| `tauri` / `tauri-build` / `tauri-specta` | 2.12.x / 2.x | Shell and typed IPC. **Tauri 3 is not stable — do not use** |
| SQLite / `rusqlite` | 3.54.1 / 0.41 | Bundled storage (`backup`, `functions`, `blob`) |
| `axum` / `sqlx` | 0.8 / 0.9 | Optional server edition; alternative driver |
| `rig` / `tokio` | 0.46 / 1.x | LLM layer; async runtime |
| `serde` / `serde_json` / `schemars` | 1 | Serialization, tool and IPC schemas |
| `thiserror` / `argon2` / `sha2` | 2 / 0.5 / 0.10 | Errors, password hashing, audit chain |
| `rust_decimal` / `chrono` / `chrono-tz` | 1.x / 0.4 / 0.10 | Ratio math, dates, `Asia/Jakarta` |
| `pdf-extract` / `lopdf` / `rust_xlsxwriter` | latest | CV text, PDF output, payroll packets |
| `lettre` / `async-imap` / `icalendar` | latest | SMTP, IMAP poll, ICS |
| `sqlite-vec` | latest | Vector search (optional) |
| `proptest` / `criterion` / `insta` | latest | Dev-only |

Pin in `Cargo.lock`; run `cargo outdated` and `cargo deny check` at each gate.

---

## 13. Acceptance criteria and parity gates

- [ ] `cargo build --workspace --release`, `cargo test --workspace`, `clippy --all-targets -- -D warnings`, `fmt --check` green on Windows and macOS.
- [ ] Parity green: zero diff outside `divergences.toml`, which has not grown.
- [ ] Audit cross-check: 500 Python entries hash identically; a one-byte edit is caught at the exact `seq`.
- [ ] Payroll: 1k < 2 s, invariants hold, THR and FINAL `spec` cases pass.
- [ ] Boundary test: no forbidden edge; `core` has no `tokio`, `reqwest`, or `rusqlite`; `cargo tree --no-default-features` has no `axum`, and the bundle contains no Python.
- [ ] IPC bindings regenerate to a no-op diff; error codes match `DomainCode` 1:1.
- [ ] Negative tests first: no mutation without `&Session`; an agent actor is rejected at deserialization.
- [ ] Cold start, IPC p95, RAM, and installer budgets met on a cold machine ([`10-quality.md`](10-quality.md)).

---

## 14. Risks and open decisions

| Risk | Mitigation |
|---|---|
| `rig` API churn before 1.0 | Wrap behind `agents::Provider` / `agents::Extractor`; only adapters import `rig` |
| Decimal parity drift | i64 sen, `MidpointAwayFromZero`, text-parsed ratios, a golden per boundary |
| Canonical JSON drift | Hand-written serializer, 500-entry cross-check, hash-stability test |
| `panic = "abort"` crash | No `unwrap` in libraries, `Result` commands, WAL autosave |
| SQLite writer contention | One writer, batched transactions, `spawn_blocking`, bench gate |
| Prompt drift / scope creep | Normalised diff test in CI; feature-gated `api`, size-checked out of the bundle |

**Open decisions:** (1) `rusqlite` vs `sqlx` — default `rusqlite`; (2) i64 sen vs
`rust_decimal` money — default i64 sen; (3) UUIDv7 vs strict v4 parity; (4) whether `api`
ships in 1.0; (5) `sqlite-vec` now or after v1; (6) prompts in-crate vs a shared repo-root
`prompts/`.
