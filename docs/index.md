# HRAgents Desktop

The HR department of one, in a box. One HR operator runs hiring, onboarding,
people records, leave, payroll preparation, growth, offboarding, and compliance
from a single local application — no server, no account, no telemetry.

[Quickstart](quickstart.md){ .md-button .md-button--primary }
[Implementation status](plan/desktop-migration/13-implementation-status.md){ .md-button }
[Decisions](adr/README.md){ .md-button }

## What it actually does

- **Evaluates candidates with a deterministic scorer.** Language models extract
  structured evidence from CVs; pure Rust code scores it. The same input scores
  the same, every time. An offline extractor is the default; a live provider
  (any OpenAI-compatible endpoint, including OpenCode Go) is optional.
- **Bounds automation in code.** Auto-scheduling needs a high score, low
  run-to-run variance, zero anomaly flags, and evidence for every dimension.
  Rejections above the merit floor require a named human sign-off.
- **Keeps one company on one machine.** A desktop install is a single-company
  SQLite database, encrypted with SQLCipher under a per-install key. There are
  no employee, manager, or candidate logins in this edition.
- **Keeps a real record.** Every consequential action is an entry in a SHA-256
  hash-chained audit log, verifiable after every restart.
- **Prepares payroll, never pays it.** Monthly, THR, and final runs with BPJS,
  PPh 21, and overtime match the parity oracle to the sen. Rate tables are
  operator-maintained and verified — never hardcoded. Money movement stays in
  the company's existing payroll process.

## The free edition, plainly

- Per-user Windows installer, no admin required.
- Unsigned build, no signing certificates, no hosted update server, no
  phone-home. Updates are a fresh installer plus a verified backup restore.
- Daily automatic backups (keep 7) plus manual encrypted `.hrbackup` sets
  (database + documents + key + SHA-256 manifest) before any update, restore,
  rekey, or erasure.
- A printed recovery key unlocks the installation when the OS key wrapper is
  lost. Support never asks for the password or the key; the `diag` bundle is
  versions, counts, and hashes only.

## Where to go next

- [Quickstart](quickstart.md) — install, first run, recovery key, first backup.
- [Product scope](plan/desktop-migration/00-product-scope.md) — who it serves
  and what it deliberately does not do.
- [Implementation status](plan/desktop-migration/13-implementation-status.md) —
  what is built, what the gates prove, what is still open.
- [Pilot plan](plan/desktop-migration/15-pilot.md) — the six-week pilot with
  entry criteria and the go/no-go template.
- [Restore drill](plan/desktop-migration/16-restore-drill.md) — verify, backup,
  restore, re-verify, including failure injection.
