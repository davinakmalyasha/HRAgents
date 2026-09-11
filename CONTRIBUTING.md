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

Read `docs/architecture/hitl-bounds.md` before touching the pipeline or decision layer.

## Development setup

Prerequisites: [uv](https://docs.astral.sh/uv/) (it installs Python 3.14 automatically)
and Git. Docker Desktop is optional — the test suite runs fully in memory with SQLite
and `fakeredis`.

```bash
git clone https://github.com/davinakmalyasha/HRAgents.git
cd HRAgents
uv sync --all-groups
uv run pre-commit install
```

Run the API locally:

```bash
uv run uvicorn hr_agents.main:app --reload
```

## The verified gate

Every change must pass — CI enforces the same commands:

```bash
uv run python scripts/check.py
```

That runs `ruff check`, `ruff format --check`, `mypy`, and `pytest`. The system runs
end-to-end without any API keys; live-model tests are opt-in scripts, not part of the gate.

## Branches, commits, PRs

- Trunk-based: `main` is protected; branch as `feat/...`, `fix/...`, `docs/...`, `chore/...`.
- [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
  `chore:`, `test:`, `refactor:`. Add `!` or a `BREAKING CHANGE:` footer for breaking
  changes. release-please turns these into the changelog and version bumps — see
  `docs/plan/release-process.md`.
- Keep PRs focused. Squash merge is the only merge method; the PR title becomes the
  commit message.
- Sign off your commits (DCO): `git commit -s`. By signing off you certify the
  [Developer Certificate of Origin](https://developercertificate.org/).

## Tests

- Never hit the network. Stub providers (`respx`, fake adapters) or use the offline
  `test` model.
- Never hardcode dates: anchor them relative to `date.today()`.
- Use in-memory stores and SQLite; Postgres-only behavior is covered by the CI
  `migrations` job.
- New behavior needs tests. Prefer negative tests for anything involving approvals,
  gates, or destructive actions.

## Docs

- Behavior changes update the docs that describe them (`docs/`, README,
  `docs/api/openapi.yaml`).
- When you complete a plan item, tick it in `docs/plan/master-build-plan.md`; open work
  lives in `docs/plan/remaining-work.md`.
- Hard-to-reverse decisions get an ADR in `docs/adr/`.

## Never commit

- `.env` or any real credential — CI scans the full history with gitleaks and GitHub
  push protection is enabled.
- Real candidate or employee data, or customer documents. Use synthetic fixtures.

## Where to start

- Issues labeled `good first issue` are scoped starter tasks.
- The README roadmap and `docs/plan/remaining-work.md` show what is next.
- Questions and ideas: [Discussions](https://github.com/davinakmalyasha/HRAgents/discussions).
