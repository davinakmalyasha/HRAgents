# AGENTS.md — instructions for AI coding agents

This file helps AI coding assistants (opencode, Cursor, Copilot, Claude Code, …)
contribute safely. Humans should read [`CONTRIBUTING.md`](CONTRIBUTING.md) instead.

## The verified gate

Run this before claiming any task is done:

```bash
cd rust
cargo test --workspace --exclude hragents-desktop
cargo clippy --workspace --exclude hragents-desktop --all-targets -- -D warnings
cargo fmt --all -- --check
```

Fix failures — never suppress them without an explicit reason. When you touch
`rust/apps/desktop/ui/`, also run `npm run typecheck` and `npm run build` there.
Docs changes must pass `mkdocs build --strict` from the repo root.

The Tauri shell crate (`hragents-desktop`) is excluded from the workspace gate
because its vendored OpenSSL build needs a working perl; check it explicitly
when you touch `rust/apps/desktop/src/`:

```bash
export PERL5LIB=/tmp/perllib MSYS2_ENV_CONV_EXCL=PERL5LIB PATH=/tmp/mkshim:$PATH
cargo check -p hragents-desktop
```

Design tokens are law: hex colors may only appear in the theme file
(a guard test fails otherwise), and status colors always ship with icon + label.

## Hard rules — never weaken these

- Agents extract/communicate only; **deterministic code decides**; a named human gates
  every consequential outcome.
- No shell or `run_command` tools, ever.
- No payment execution (payroll is prepare/verify/export only).
- No auto-rejection; rejections above the merit floor require a named human sign-off.
- No hardcoded statutory rates — operator-maintained rate tables with a `verified` gate.
- No secrets, `.env`, or real personal data in commits.

## Session ritual

1. Read `docs/plan/master-build-plan.md` (the source of truth) and the relevant
   `docs/` file before editing.
2. When behavior changes, update the docs that describe it.
3. Tick completed items in `docs/plan/master-build-plan.md`; keep
   `docs/plan/desktop-migration/13-implementation-status.md` accurate for open work.
4. End the session with a green gate and a summary of what changed.

## Test conventions

- No network access; no real LLM calls (the offline keyword extractor and the
  recorded provider replay are the test doubles; live tests are `#[ignore]`d).
- No hardcoded dates — anchor to `business_today()` (never `date.today()`: the host is UTC
  while the business day is `Asia/Jakarta`; a guard test enforces it).
- In-memory stores and SQLite in tests; SQLCipher paths are covered with the
  `sqlcipher` feature.
- Negative tests first for approvals, gates, retention/purge, and overrides.

## Code conventions

- Rust 2024 edition, full type hints via the type system; `serde` models at boundaries.
- Ruff line length 100 still applies to any remaining Python (docs tooling only);
  mathematical notation in docstrings is intentional.
- Do not add comments unless they explain non-obvious decisions.
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`), signed off
  (`git commit -s`).
