# 15 — Six-week pilot plan

**Status:** draft · **Gates:** 5/6 candidate · **Date:** 2026-11-02 · **Related:** [`12-impact.md`](12-impact.md) (§8–9), [`13-implementation-status.md`](13-implementation-status.md) (gate table), [`14-release-drill.md`](14-release-drill.md)

Gates G0–G4 pass on the dev slice only. G5 (no-Python cutover) and G6
(signed installer + pilot) are open: code signing needs human-enrolled
certificates and has not happened. Nothing here claims G5 or G6 is passed.
No pilot starts until the entry criteria in §1 are all green.

## 1. Entry criteria (all must be true before recruiting pilots)

| # | Criterion | Evidence |
|---|---|---|
| E1 | Installable free build for the pilot OS (Windows first) | Per-user NSIS installer runs without admin; SHA-256 recorded; clean-VM install checklist green. **No certificate is required** — the pilot is free. |
| E2 | Backup/restore drill evidence | `16-restore-drill.md` run green on the release build: verify → backup → restore → re-verify, plus failure-injection and rollback rehearsal, with a signed-off table |
| E3 | Support channel live | Office-hours channel exists (WhatsApp group or email), named support contact, response-time promise (§6); backup-verification cadence agreed |
| E4 | Demo company + first-run wizard tested with a non-technical user | Install → first record < 5 min observed, zero terminal use |
| E5 | Accountant-reviewed payroll packet | One XLSX review packet from demo data reviewed and accepted by an accountant (no software cost) |
| E6 | Diagnostic-bundle PII check | Fixture test confirms `.hrdiag` contains no PII/secrets before any upload is enabled |

If any row is red, recruiting does not start. Unsigned smoke builds from
`release-desktop.yml` are never pilot builds.

## 2. Pilot company profile

- Indonesian SME, 30–150 employees.
- HR function of 1–2 people (the HR generalist is the operator; the second
  person, if any, is the named sign-off for approvals).
- One hiring cycle and one payroll cycle observable during the six weeks.
- One Windows laptop available as the HR machine (Windows first per §12-§9;
  macOS only after the Windows installer and updater are stable).
- Willing to print and file the recovery key and to follow the backup cadence.
- Two pilot companies (target per `12-impact.md` §4 adoption metrics).

Recruiting screen: exclude companies that need employee/manager self-service
logins now (non-goal, §8), need a server edition (non-goal, §8), or cannot
name the single HR operator who owns the laptop.

## 3. Week-by-week schedule

| Week | Focus | Activities | Done when |
|---|---|---|---|
| 0 (pre) | Baseline | Observe one hiring cycle + one payroll cycle as-run: record time spent, tools used, failure points | Baseline sheet filled (§4 "before" column) |
| 1 | Install + import | Signed installer on the HR laptop; first-run wizard; import 20–50 employees; print recovery key; first manual backup + verify | Install → first record < 5 min; `verify` ok; recovery key printed and filed |
| 2–3 | Hiring cycle | Import CVs; run one real hiring cycle: extract → score → evidence review → gated decision (reason + sign-off recorded) | ≥1 evaluated candidate; every rejection above the merit floor has reason + named sign-off; 0 forgotten follow-ups (Today + reminders) |
| 4 | Payroll cycle | Seed/verify rate tables (verified gate); compute monthly run; review anomalies; approve; export XLSX packet | 50-employee run < 15 min; packet reviewed; rates traceable to source |
| 5 | Daily use | Today inbox + Ask daily; policy questions answered with citations; onboarding/document requests as needed | Ask answers < 30 s with citation; decision reconstruction < 1 min |
| 6 | Exit interview | Measure "after" metrics; interview the HR operator; collect top-5 friction points; decide continue / narrow / stop | §4 table filled; §7 go/no-go recorded |

## 4. Before/after metrics (targets from `12-impact.md` §4)

| Metric | Before (week 0) | After (week 6) | Target |
|---|---|---|---|
| Install → first record | n/a | measured | < 5 min |
| Install → first evaluated candidate | n/a | measured | < 10 min |
| Monthly payroll assembly (50 employees) | 1–2 days | measured | < 15 min |
| Shortlist per candidate | hours across tabs | measured | < 10 min |
| Policy question answer | minutes of searching | measured | < 30 s with citation |
| Decision reconstruction | email archaeology | measured | < 1 min |
| Forgotten follow-ups per hire | several | counted | 0 |
| Rejections above merit floor without reason | unknown | counted | 0 |
| Users needing a terminal | — | counted | 0 |
| "Where do I click?" tickets | — | counted | 0 in pilot |
| Cold start / idle memory / installer | — | measured | ≤ 1.5 s / < 150 MB / ≤ 35 MB |
| Backup verification | — | measured | 100% |
| Audit verify after restart | — | measured | always passes |

Record the tool or command used for each "after" value (stopwatch, `verify`
output, payroll timestamps). A target with no recorded evidence counts as missed.

## 5. Data-handling rules

- The company HR data is a **local encrypted database on the HR laptop only**. The key file is protected by Windows DPAPI and must be backed up separately; losing it loses the data.
  There is no SaaS tenant and no server copy.
- The **recovery key is printed on paper** at setup, filed by the operator, and
  never sent over the support channel.
- Backups: daily automatic (keep 7) plus manual `.hrbackup` export before any
  update, restore, rekey, or erasure. Each backup is verified at creation.
- Support never asks for the database password or recovery key. Diagnostic
  bundles (`.hrdiag`) are PII-free by fixture test before upload; nothing
  uploads without operator consent.
- **At pilot exit:** the company chooses — (a) keep running on the pilot build
  with continued backup cadence, or (b) verified export of their data plus
  witnessed deletion of the local DB and all backup copies held for the pilot.
  The choice and its completion are recorded in the exit interview.

## 6. Support runbook

- **Channel:** one office-hours channel per pilot (WhatsApp group or email with
  a named support contact). Posted hours, promised first response (next
  business day at latest), and an escalation name.
- **Backup verification cadence:** operator runs `verify` weekly and posts the
  one-line result; support checks daily automatic backups exist (keep 7) at
  each weekly check-in. Any failed verification is a stop-work event until
  resolved.
- **Incident triage:** (1) capture `.hrdiag` (PII-free); (2) `verify` the live
  DB and the latest backup; (3) do not touch the live DB until both results
  are recorded.
- **Rollback = reinstall + restore verified backup.** There is no in-place
  downgrade. Steps: reinstall the previous signed build (cached installer in
  `updates/cache/`, kept 7 days, or fresh download), restore the latest
  verified pre-update backup per `16-restore-drill.md`, re-run `verify`, resume.
  Rehearsed before the pilot counts as entry evidence (E2).

## 7. Exit criteria and go/no-go decision template

Exit interview completes when: §4 table filled with evidence, operator
interviewed, top-5 friction points listed, pilot-data choice (§5) executed.

```text
Pilot go / no-go — company: ____________  date: ____________
Operator: ____________  Support: ____________  Build: ____________

Metrics: [ ] all §4 targets met with evidence / misses: ____________
Friction top-5: 1.____________ 2.____________ 3.____________
  4.____________ 5.____________
Backup/audit: [ ] weekly verifies green [ ] audit verify passes after restart
Pilot data: [ ] keep running [ ] exported + deleted (witness: ____________)

Decision (one): CONTINUE (expand) / NARROW (fix scope: ____________) / STOP
Reason: ____________
Named sign-off: ____________  date: ____________
```

"Go" for public beta additionally needs: docs + demo company + crash
diagnostics + update channel (per `12-impact.md` §9), and G5/G6 closed.

## 8. Explicit non-goals

- **No employee/manager logins during the pilot.** Single HR operator only;
  no self-service accounts, no shared passwords.
- **No server edition promises.** If manager/employee access demand appears,
  it is recorded as a finding, not committed as a feature.
- **No payroll execution.** Preparation, verification, and export only; money
  movement stays in the company's existing payroll process.
- **No auto-rejection.** Rejections above the merit floor require a named
  human sign-off; this rule is not relaxed for pilot speed.
- **No hardcoded statutory rates.** Rate tables stay operator-maintained with
  the verified gate; pilot pressure does not bypass it.
