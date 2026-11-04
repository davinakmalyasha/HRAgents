# Contributing to HRAgents

Thanks for considering it. This project exists so a single HR person can serve a whole
company without skipping the human parts. Contributions that strengthen that are welcome.

## Ground rules

These are product invariants, not preferences — PRs that weaken them are declined:

- Agents extract and communicate; deterministic code decides; a named human gates every
  consequential outcome (rejections, offers, final pay, erasure).
- No shell/command tools, ever. Tools are typed and least-privilege.
- No payment execution: payroll is prepare, verify, export — never send.
- No auto-rejection, no anonymous overrides, no training on historical hiring outcomes.
- Statutory numbers are never hardcoded; they come from operator-maintained rate tables.
- DeepSeek V4.1 Flash is the only live model — no other model is configured or tested.

Read `docs/archive/python-server/architecture/hitl-bounds.md` before touching the pipeline or decision layer.

## Development setup

Prerequisites: Rust 1.99 (see `rust/rust-toolchain.toml`), Node 26 (see
`rust/apps/desktop/ui`), and Git. No Python, no Docker, no database server —
everything runs locally against SQLite.

```bash
git clone https://github.com/davinakmalyasha/HRAgents.git
cd HRAgents
cd rust && cargo test --workspace --exclude hragents-desktop
```

Run the desktop app:

```bash
cd rust
cargo run -p hragents-cli -- demo target/demo.db
cargo run -p hragents-cli -- verify target/demo.db
```

The UI preview (`rust/apps/desktop/ui`, `npm install && npm run dev`) uses the
same typed command names as Tauri and the same gates; it is a review surface,
not a second implementation.

## The verified gate

Every change must pass — CI enforces the same commands:

```bash
cd rust
cargo test --workspace --exclude hragents-desktop
cargo clippy --workspace --exclude hragents-desktop --all-targets -- -D warnings
cargo fmt --all -- --check
```

When you touch `rust/apps/desktop/ui`, also run `npm run typecheck` and
`npm run build` there. Docs changes must pass `mkdocs build --strict`.
Live-provider tests are ignored by default and never run in CI; the offline
extractor and the recorded replay are the gate.

## Branches, commits, PRs

- Trunk-based: `main` is protected; branch as `feat/...`, `fix/...`, `docs/...`, `chore/...`.
- [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
  `chore:`, `test:`, `refactor:`. Add `!` or a `BREAKING CHANGE:` footer for breaking
  changes.
- Keep PRs focused. Squash merge is the only merge method; the PR title becomes the
  commit message.
- Sign off your commits (DCO): `git commit -s`. By signing off you certify the
  [Developer Certificate of Origin](https://developercertificate.org/).

## Tests

- Never hit the network. The offline keyword extractor and the recorded provider
  replay are the test doubles; live tests are `#[ignore]`d and keyed.
- Never hardcode dates: anchor to `business_today()` (never `date.today()` — the
  host is UTC while the business day is `Asia/Jakarta`).
- In-memory stores and SQLite in tests; SQLCipher paths are covered with the
  `sqlcipher` feature.
- New behavior needs tests. Prefer negative tests for anything involving approvals,
  gates, retention/purge, or destructive actions.

## Docs

- Behavior changes update the docs that describe them (`docs/`, README).
- When you complete a plan item, tick it in `docs/plan/desktop-migration/13-implementation-status.md`.
- Hard-to-reverse decisions get an ADR in `docs/adr/`.

## Never commit

- `.env` or any real credential — CI scans the full history with gitleaks and GitHub
  push protection is enabled.
- Real candidate or employee data, or customer documents. Use synthetic fixtures.
- The live database (`hragents.db`) or the install key (`hragents.key`).

## Where to start

- Issues labeled `good first issue` are scoped starter tasks.
- The [implementation status](docs/plan/desktop-migration/13-implementation-status.md)
  shows what is done and what is deliberately still missing.
- Questions and ideas: [Discussions](https://github.com/davinakmalyasha/HRAgents/discussions).
