# HRAgents Desktop — Rust workspace

This workspace is the desktop runtime: one Rust process, one SQLite file, no Python,
no localhost server, no Docker. The Python product under `../src/` remains the
reference oracle until Gate 5.

```text
crates/hragents-core      pure domain: money, time, audit, auth, people, hiring,
                          leave, payroll, approvals, compliance, policy
crates/hragents-store     SQLite schema, migrations, FTS5, repositories, backup
crates/hragents-agents    deterministic extraction + policy-answer contracts
crates/hragents-ipc       application services shared by Tauri commands and the CLI
crates/hragents-cli       demo / verify / backup harness
apps/desktop              Tauri 2.12 shell + typed commands
apps/desktop/ui           React 19 + Vite 8 + TypeScript 7 desktop UI
```

Dependency direction is one-way: `core ← store ← ipc ← desktop`. `core` never
imports Tauri, SQLite, network, or UI.

## Run

```bash
cd rust
cargo test --workspace --exclude hragents-desktop
cargo clippy --workspace --exclude hragents-desktop --all-targets -- -D warnings
cargo run -p hragents-cli -- demo target/demo.db
cargo run -p hragents-cli -- verify target/demo.db
cargo build -p hragents-desktop
```

The release benchmark is explicit:

```bash
cargo test -p hragents-ipc --release payroll_1000 -- --ignored --nocapture
```

Current result: **1,000 lines in ~13 ms** against a 2 s budget.

## Parity

`../scripts/parity_export.py` generates fixtures from the Python implementation;
`crates/hragents-core/tests/python_parity.rs` fails the build if Rust diverges.
Covered now: money parsing/rounding/operations, audit hashes and chaining, progressive
PPh 21, and the scoring aggregate (mean, weighted mean, population σ).

## Encryption

`hragents-store` exposes `Store::open_encrypted` only with the `sqlcipher` feature:

```bash
cargo build -p hragents-desktop --features hragents-store/sqlcipher
```

The default build is plain SQLite so tests do not require an OpenSSL toolchain.
A release is not Gate 0-complete until the SQLCipher build and a reopen/rekey test
are green.

## UI

```bash
cd apps/desktop/ui
npm install
npm run dev        # browser preview, same command names, demo data
npm run build      # typecheck + production bundle
```

The packaged Tauri app uses the real Rust commands; browser preview uses an in-memory
adapter with the same shapes. It never touches a database.

## Status

See `../docs/plan/desktop-migration/13-implementation-status.md` for what is actually
green, what is partial, and the next ten tasks. Do not describe a partial gate as
complete.
