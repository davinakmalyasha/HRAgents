## What & why

<!-- One paragraph: what changed and why. Link the issue: Closes #123 -->

## Checklist

- [ ] Conventional Commit title (`feat:`, `fix:`, `docs:`, `chore:`, …)
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy` passes
- [ ] `uv run pytest` passes
- [ ] Docs updated where behavior changed (`docs/`, README, and the
      `docs/plan/master-build-plan.md` checkbox if a phase item is done)
- [ ] No secrets, no `.env`, no real candidate or employee data
- [ ] Human-in-the-loop rules unchanged — or the change is discussed below

## Notes for reviewers

<!-- Tradeoffs, follow-ups, screenshots for UI changes -->
