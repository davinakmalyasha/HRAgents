# Quickstart

Fifteen minutes, one Windows laptop, no cloud keys, no admin rights.

## 1. Install

Run the per-user installer (`HRAgents_0.1.0_x64-setup.exe`). It installs for
the current Windows user only — no administrator prompt, no system-wide
changes. Data survives uninstall; the installer never touches it.

## 2. First run

The first-run wizard asks for three things:

1. The company name.
2. The HR operator's name and username.
3. A password (Argon2id-hashed; it also unlocks the idle lock).

## 3. File the recovery key

Open **Settings → recovery** and print the 64-hex recovery key on paper, then
file it where the company keeps important documents. If the Windows key
wrapper is ever lost, the pre-login recovery screen re-opens the installation
with this key — and nothing else will. Support never asks for it.

## 4. Make the first backup

Run **Settings → backup** (or `hragents-cli backup-set`) and store the
`.hrbackup` file off the machine. Then run verify: a green integrity result
plus a passing audit chain is the definition of "it works".

## 5. Bring existing data (optional)

If you have a `hragents-export/1` JSON file produced by the legacy bridge
before the Gate 5 cut, dry-run first, then commit on the HR laptop:

```bash
hragents-cli import hragents-export.json           # validates, writes nothing
hragents-cli import hragents-export.json --commit  # one transaction per slice
```

Org units, employees, leave, approved payroll runs, and audit history import
slice by slice; every slice is idempotent, and a re-run is a no-op. Tables
outside those slices are reported with their row counts, never silently
dropped. The legacy export bridge itself was removed at the cut — no new
export files can be produced — but files generated earlier still import.
Details: [implementation status](plan/desktop-migration/13-implementation-status.md).

## 6. Live provider key (optional)

Extraction works offline out of the box. To use a hosted model (any
OpenAI-compatible endpoint, including OpenCode Go), put the key in the
**shell's** environment — `.env` files are not read automatically:

```bash
export OPENCODE_API_KEY='paste-key-here'
```

(`set -a; source .env; set +a` loads the repo `.env` for the session instead.
The desktop app and `cargo` never read `.env` themselves; docker compose and
the Python provider layer do, which is the whole confusion — see
`.env.example`.)

## 7. Agent helpers

Every screen has a helper that reads and explains — never decides:

- **Today** opens with a morning briefing: approvals, queued messages,
  payroll awaiting sign-off, expiring documents.
- **Reports** ranks applicants per job with scores and flags.
- **Pay** shows a plain-words readiness checklist per run.
- **People** shows attendance findings and document attention items.
- **Ask** answers policy questions with citations, offline by default.
  With a provider key, DeepSeek V4.1 Flash may rephrase the answer;
  citations never change.

Draft, preview, then **you** check with your password and send, approve,
or lock. Nothing sends, approves, or pays on its own.

## Next

- [Product scope](plan/desktop-migration/00-product-scope.md) — who it serves
  and what it deliberately does not do.
- [Pilot plan](plan/desktop-migration/15-pilot.md) — entry criteria, the
  six-week schedule, and the support runbook.
- [Restore drill](plan/desktop-migration/16-restore-drill.md) — the rehearsal
  that makes backups trustworthy.
