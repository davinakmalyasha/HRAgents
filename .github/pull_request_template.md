## What & why

<!-- One paragraph: what changed and why. Link the issue: Closes #123 -->

## Checklist

- [ ] Conventional Commit title (`feat:`, `fix:`, `docs:`, `chore:`, …), signed off (`git commit -s`)
- [ ] Rust gate green: `cargo test`, `clippy -D warnings`, `fmt --check`
      (plus `npm run typecheck` + `npm run build` for UI changes)
- [ ] Docs updated where behavior changed (`docs/`, README,
      and the `13-implementation-status.md` entry if a plan item is done)
- [ ] No secrets, no `.env`, no real candidate or employee data
- [ ] Human-in-the-loop rules unchanged — or the change is discussed below

## Notes for reviewers

<!-- Tradeoffs, follow-ups, screenshots for UI changes -->
