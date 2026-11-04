# Architecture Decision Records

Immutable notes for decisions that are expensive to reverse. Each ADR states the
context, the decision, and the consequences we accept. The locked-decisions table in
[`docs/plan/master-build-plan.md`](../plan/master-build-plan.md) stays the summary;
ADRs add the reasoning, and are citable in the paper.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-llm-extracts-deterministic-scores.md) | LLMs extract; deterministic code scores | Accepted |
| [0002](0002-hitl-bounds-in-code.md) | Human-in-the-loop bounds enforced in code | Accepted |
| [0003](0003-no-shell-tools.md) | No shell or command tools, ever | Accepted |
| [0004](0004-provider-layer.md) | Capability/provider abstraction for every external dependency | Accepted |
| [0005](0005-sync-domain-async-edge.md) | Synchronous domain layer; async only at the agent and network edge | Accepted |
| [0006](0006-tenancy-rls.md) | Single schema with `tenant_id` and forced row-level security | Accepted |
| [0007](0007-tauri-2-desktop-shell.md) | Tauri 2.12.x desktop shell, not Electron and not Tauri 3 | Accepted |
| [0008](0008-rust-core-in-process-ipc.md) | Rust core in-process behind typed Tauri IPC; no localhost HTTP, no Python sidecar | Accepted |
| [0009](0009-sqlite-rusqlite.md) | SQLite 3.54.1 via rusqlite 0.41; one database file per company | Accepted |
| [0010](0010-one-company-per-install.md) | One company per install; no `tenant_id` or RLS in the desktop schema | Accepted |
| [0011](0011-single-hr-operator-role.md) | One `hr_operator` role, 1–3 local accounts, local login | Accepted |
| [0012](0012-encryption-at-rest.md) | SQLCipher on by default with an Argon2id key hierarchy and OS keychain | Accepted |
| [0013](0013-money-integer-sen.md) | Money as integer sen (`i64`); no floats; explicit half-away-from-zero rounding | Accepted |
| [0014](0014-rust-llm-layer-rig.md) | Rust LLM layer on `rig` 0.46; output validated in Rust; agents never decide | Accepted |
| [0015](0015-python-parity-oracle.md) | Python remains the offline parity oracle until Gate 5, never in the installer | Accepted |
| [0016](0016-server-edition-boundary.md) | Desktop stays single-machine; a future Axum/Postgres edition reuses the Rust core | Accepted |

New ADRs: copy the format of an existing file, number sequentially, open a PR.
ADRs are append-only — to change a decision, add a new ADR that supersedes the old one
and update its status line.
