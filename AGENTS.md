# AGENTS.md — instructions for AI coding agents

This file helps AI coding assistants (opencode, Cursor, Copilot, Claude Code, …)
contribute safely. Humans should read [`CONTRIBUTING.md`](CONTRIBUTING.md) instead.

## The verified gate

Run this before claiming any task is done:

```bash
uv run python scripts/check.py
```

It runs `ruff check`, `ruff format --check`, `mypy`, and `pytest` (838 tests, ≥90%
coverage enforced in CI). Fix failures — never suppress them (`# type: ignore`,
`noqa`, skipped tests) without an explicit reason.

When you touch `web/`, also run the dashboard gate:

```bash
cd web && npm run lint && npm run format:check && npm run typecheck && npm run test && npm run build
```

Design tokens are law: hex colors may only appear in `web/src/styles/theme.css`
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
   `docs/plan/remaining-work.md` accurate for open work.
4. End the session with a green gate and a summary of what changed.

## Test conventions

- No network access; no real LLM calls (the offline `test` model exists for this).
- No hardcoded dates — anchor to `date.today()`.
- In-memory stores and SQLite in tests; Postgres-only paths are covered by CI.
- Negative tests first for approvals, gates, retention/purge, and overrides.

## Code conventions

- Python 3.14, full type hints, Pydantic v2 models at boundaries.
- Ruff line length 100; mathematical notation in docstrings is intentional.
- Do not add comments unless they explain non-obvious decisions.
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`), signed off
  (`git commit -s`).
