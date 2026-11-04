# 07 — UI/UX: the HR cockpit

**Draft for review · Tauri 2.12 · default 1280×860, min 1024×700**

One HR team (1–3 operators), one company. The app shows Rina what needs her, clears it fast, and leaves proof.

## 1. Design principles

- **Person-first.** Name + role lead; never IDs.
- **One primary.** One accent button per screen, tied to its purpose.
- **State visible.** Icon + label + timestamp; agent work in plain language, never a spinner.
- **Receipts.** Every consequential action ends with who, what, when, reason, audit ref.
- **No UUIDs.** Short refs only: `#A-1042`, `#P-0187`, `#R-2026-03`.
- **No dead ends.** Empty states act; errors retry or escape; records link sideways.
- **Keyboard first.** Every action has a key; lists use `j/k`; focus is never lost.
- **Calm density.** Borders and whitespace; color is signal, ≤5% of pixels.
- **No agent personas.** Describe the work, not the worker.

## 2. Information architecture

| Surface | Question | Contains |
|---|---|---|
| **Today** | What needs me now? | Decision inbox, watching list, today's interviews and starts |
| **Hire** | Who are we hiring? | Jobs, pipeline, candidate list, CV import, case file |
| **People** | Who works here? | Directory, person profile, onboarding, leave, growth, offboarding |
| **Pay** | What do we owe? | Runs, inputs, anomalies, rates, export packets |
| **Ask** | What does policy say? | History, cited answers, handoff to a surface |
| **Settings** | How is this install set up? | Company, operators, providers, backup, updates, compliance, diagnostics |

The 10-workspace × Board/Queue/Chat model is removed. Approvals → Today; Policy → Ask; Records, onboarding, leave, growth, offboarding → People; Compliance → Settings; workspace chat → one Ask surface with visible scope. A surface is a place, not a mode.

Five surfaces plus **Settings**, which is configuration rather than a workspace.

```
Today ─┬─ decision ──────────► source record (Hire · People · Pay)
       └─ watching ──────────► source record

Hire ── jobs ── pipeline ── case file ──► hire ──► People (prefilled profile)
                              └─ schedule ──► Today

People ── directory ── profile ─┬─ onboarding
                                ├─ leave
                                ├─ growth
                                ├─ offboarding
                                ├─ payroll history ──► Pay run
                                └─ documents / consent ──► Settings ▸ Compliance

Pay ── runs ── run detail ── input ──► person profile
  └─ rates ──► Settings ▸ Compliance (verified gate)

Ask ── answer ── citation ──► exact record and field
  └─ handoff ──► prefilled action (never executes)

Settings ── company · operators · providers · backup · updates · compliance · diagnostics
```

**Cross-links.** Person chips open a 400px panel (`?panel=person:P-0187`; back closes). Today focuses the exact source control; Ask citations highlight the cited field. Hiring creates the People profile once; Hire shows "Hired → P-0187".

## 3. Screen specs

Shell: 240px rail (Today, Hire, People, Pay, Ask; Settings pinned bottom), 56px title bar with company
name, search, offline/update status, operator menu.

Every route defines empty, loading, and error states; rows note only where they differ. Loading never
replaces the header, and an error never clears the last good data.

| Screen | Layout · header · primary · states | Keys |
|---|---|---|
| **Today** `/` | 880px column: Needs you (blocking, by deadline), Watching, schedule. Header: date, count. Primary: first decision's verb. Cards: type, person + role, why, SLA, source. Empty: "Nothing needs you." Loading: 3 skeletons. Error: retry keeps list. | `j/k` `Enter` `d` snooze 4h `g t` |
| **Hire** `/hire` | Header: job, 47 candidates, closing date. Table-first pipeline (board toggles): Candidate, Stage, Score, σ, Flags, Wait, Next. Jobs: status, owner, count. Import: full-window drop zone. Primary: `Import CVs` (or `Add candidate`). Empty: "Drop CVs anywhere, or add one by hand." Error: per-file rows, partial banner. | `Cmd/Ctrl+I` `/` `x` `j/k` `b` board |
| **Candidate** `/hire/c/:ref` | See §3.1. | `a r o s m` |
| **Decision** `/d/:ref` | Two columns: "What this is" (person, source, policy clause, evidence) and "What happens if you approve" (message, effective date, reversibility). Header: type, person, deadline, why gated. Primary: `Sign rejection` / `Approve leave`, disabled until required fields (reason for rejection); signing needs fresh re-auth (≤5 min). After: receipt replaces form. Error: "Already handled by Rina at 14:02", never 404. | `Enter` sign `Esc` back |
| **People** `/people` | Table: Name, Role, Team, Start, Status, Next date; saved views. Primary: `Add person`. Profile: one scroll with sticky section rail (Contact, Employment, Compensation, Documents, Leave, Payroll, Onboarding, Growth, Offboarding, Timeline), one action each. Missing field: "Not recorded" + action. Loading: section skeletons. | `j/k` `Enter` `e` edit `/` filter |
| **Onboarding** `/people/onboarding` | Three panes: people in flight; checklist Before day 1 / Day 1 / Week 1 / Day 30; documents, blockers. Owners are free-text names/teams (IT, Finance), never accounts. Primary: next blocker (`Request document`). Empty: "No one is onboarding." Error: task rollback + inline message. | `space` done `r` remind `n` note |
| **Leave** `/people/leave` | "Who's out" board, month calendar with regional holidays, request list. Primary: `Review request`, else `New request`. Detail: balance math, policy clause, conflicts; approve/reject need named sign-off, rejection a reason. Empty: "Nobody is away in November." Error: retry keeps calendar. | `[` `]` month `t` today |
| **Pay** `/pay` | Runs: Period, Status (Draft → Locked → Reviewed → Exported), Headcount, Changes, Anomalies. Detail: summary strip, anomalies first, inputs with change markers; edits open a form + diff, never raw JSON; locking needs a named operator. Primary: `Resolve anomalies`, else `Export review packet` (XLSX + PDF, hash receipt). Rates: effective-dated, verified + source, history, impact. Empty: "No run. Copy October." Export error: stays unlocked, retry. Always: "HRAgents prepares payroll. It never pays." | `e` export `j/k` |
| **Growth** `/people/growth` | Cycles → detail with Cycle / Forms / Summaries / Goals tabs (separate objects). Primary: `Open cycle` or `Send reminders`; sharing a summary needs sign-off and shows exact text. Drafts labeled "Draft — not shared". Ratings never auto-assigned; progress needs evidence. Empty: "No cycle open." | `g g` |
| **Offboarding** `/people/offboarding` | Checklist by phase (Notice, Last week, Last day, After), asset table (item, tag, returned, date), manual access-revocation checklist, final-pay card linking to Pay. Primary: next blocker (`Confirm asset return`). Delete profile needs export-first and typed confirmation. | `space` `j/k` |
| **Compliance** `/settings/compliance` | Audit explorer (actor, entity, date, action; before/after; "Verify chain" → "142,318 entries verified"); retention policies with dry-run counts; erasure queue with legal-hold check; rate tables. Erasure: preview → export → type name + reason → erase → tombstone receipt. Never one click. | `/` filter `Enter` expand |
| **Ask** `/ask` | History (260px), thread, sources. Scope chips: Policy, People, Hiring, Pay; money and candidate data off by default, opt-in shown in the footer. Answers: direct answer + citations (doc, section, updated, quote). `Handoff` prefills an action: "Review and sign in Hire." Empty: 3 suggested questions. Offline: "Ask needs a model. Document answers are unavailable offline." | `Cmd/Ctrl+Enter` send `Esc` stop `/` focus |
| **Settings** `/settings` | Company (name, address, timezone, currency); Operators (1–3 local accounts, all "HR operator", no role picker); Providers (keys, test, offline mode); Backup & restore (encrypted path, last backup, typed-confirm restore); Updates (signed, restart when idle); Compliance (audit, retention, erasure, rates); Diagnostics (logs, DB integrity). One primary per section. No hidden `/ops`. | `Cmd/Ctrl+,` |
| **Login / first run** `/login` | Local email + password; optional OS re-auth (Windows Hello / Touch ID) for fresh actions, never for unlock; recovery code printed at setup, no email reset. Lock after 10 min idle. First run: Company → Operator → Providers (skippable) → Import or empty → Backup path; ends with a ready receipt. | `Enter` `Cmd/Ctrl+Shift+L` lock |

### 3.1 Candidate case file

```
┌ Budi Santoso · Backend Engineer · #A-1042        [ Advance ▾ ] ┐
│ ✓ Consent 12 Oct · budi@… · +62 812…    ⚑ 1 flag · σ 0.03      │
├──────────────────────────────┬─────────────────────────────────┤
│ CV — PDF, page 3 of 4        │ WHY THIS SCORE                  │
│ [ rendered page ]            │ Technical depth  0.82  exp §2   │
│                              │ Stack alignment  0.91  repo     │
│                              │ Systems          0.74  §4       │
│                              │ [formula, weights, evidence]    │
├──────────────────────────────┴─────────────────────────────────┤
│ Timeline  received → extracted → scored → awaiting you         │
└────────────────────────────────────────────────────────────────┘
```

Split view: CV left (55%), evidence right; divider persisted. Sticky header: name, job, ref, contact, consent, score, sigma, flags. Score 0.00–1.00, two decimals, gray bars (never red/green); click opens formula, weights, evidence. Flags: amber chip with reason. Timeline append-only with actor + time. Primary `Advance`; `Reject` in overflow needs reason, note, sign-off, message preview. `Offer`, `Schedule`, `Message` secondary. No consent: message disabled + `Request consent`. Empty CV: "No CV on file — request one." Render error: "Open in system viewer."
Keys: `a` advance, `r` reject, `o` offer, `s` schedule, `m` message, `j/k` next/prev, `e` evidence, `[` `]` resize, `Esc` back.

## 4. Visual system

- **Type:** Inter; 14/20 body, 16/24 section, 20/28 screen, 24/32 page; 12px metadata only. JetBrains Mono, tabular numbers. Two weights per screen.
- **Space:** 4px base; page padding 24/32; rows 32–40; controls 32; radius 6/10; one overlay shadow.
- **Color:** monochrome + one accent `#2563EB` (`#3B82F6` dark); amber/red/green status, always icon + label; hex only in the theme file.
- **Cards:** discrete decisions or records only, never nested.
- **Tables:** sticky header, no zebra, right-aligned numbers, column chooser, saved views, actions in overflow.
- **Forms:** label above, helper text, validate on blur, error summary; never placeholder-as-label.
- **Dialogs:** 480/640px; focus trap; `Esc` cancels unless dirty; `Cmd/Ctrl+Enter` submits.
- **Toasts:** 4s, one action; never the only record — the receipt is.
- **Skeletons:** row-shaped; no spinner over 400ms; optimistic where reversible.
- **Density:** 20–40 rows at 900px; no hero panels; object headers carry real facts, never a title over an empty toolbar.

## 5. Desktop interactions

**Menu:** File (Import, Export, Backup, Quit) · Edit · View · Window · Help (shortcuts, diagnostics, about).

| Keys | Action | Keys | Action |
|---|---|---|---|
| `Cmd/Ctrl+K` | Command palette | `g` `t/h/p/y/a/s` | Go to Today/Hire/People/Pay/Ask/Settings |
| `Cmd/Ctrl+1…5` | Surfaces | `j` `k` | Next / previous row |
| `Enter` | Open | `Esc` | Close, else back |
| `/` | Filter or composer | `x` | Multi-select; `Shift`+click ranges |
| `Cmd/Ctrl+I` | Import CVs | `Cmd/Ctrl+Z` | Undo safe actions |
| `?` | Shortcut sheet | `Cmd/Ctrl+Shift+L` | Lock |

- **Drag-drop:** dropping anywhere in Hire opens a tray: "Drop 12 CVs to import (PDF, DOCX)". Per-file progress, named errors, dedupe before write; Tauri native event.
- **Bulk:** safe only — tag, archive job, export, send reminder, assign template, finish tasks. Reject, approve leave, edit pay, delete, erase are absent, not disabled.
- **Panels and windows:** panels are 400px and route-addressable, `Esc` restores focus; the rail collapses below 1100px; minimum 1024×700, no mobile reflow.
- **Offline:** all reads/writes hit local SQLite; provider actions show "Offline — paused"; messages "Queued, sends when online". Updates are a title-bar dot; restart only when idle.

## 6. Accessibility

- WCAG 2.2 AA: 4.5:1 body, 3:1 large text and UI boundaries, both themes.
- 2px accent focus ring; full keyboard: roving tabindex, dialog trap/restore, stage menu as drag alternative.
- Route change focuses `h1` and is announced to screen readers; async results use `aria-live="polite"`.
- Scores expose `role="progressbar"` with `aria-valuetext="0.82 out of 1.00, uncertainty 0.03"`; status is text.
- Reduced motion disables transitions and streaming; 200% zoom usable; 24×24 targets.
- `axe-core` on every route and Storybook story in CI: zero serious or critical.

## 7. Internationalisation

English + Bahasa Indonesia at parity, enforced by a key-parity test and an ESLint rule banning literal user-facing strings. ICU plurals; formal "Anda" in Indonesian.

| Concern | Rule |
|---|---|
| Timezone | `Asia/Jakarta` default, display `WIB`, store UTC; use `business_today()`, never `date.today()` |
| Dates | `Intl.DateTimeFormat(locale)`: "1 Nov 2026", 24-hour times; relative time only as supplement |
| Money | `Intl.NumberFormat(locale, {currency:'IDR', maximumFractionDigits:0})` → `Rp1.250.000`, mono/tabular |
| Enums | Map to keys (`leave.status.approved`); never render the raw value |
| Errors | Server code → message; unknown code → fallback + reference |
| Switch | Instant, no reload, persisted per OS user, `<html lang>` updated; exports use active language |

## 8. Content and microcopy

| Moment | Write | Not |
|---|---|---|
| Error | "We couldn't save the score. Your edits are still here. Try again, or copy reference A-1042-7f." | "Something went wrong." |
| Empty | "No candidates yet. Drop CVs anywhere in this window, or add one by hand." | "No data." |
| Confirm | "Sign rejection for Siti Rahma? She'll receive the feedback message after you sign. This can't be unsent." | "Are you sure?" |
| Receipt | "Recorded: rejection sign-off · Siti Rahma · reason: skill mismatch · Rina (HR) · 1 Nov 2026 14:32 WIB · audit #8f3c2a." | "Success." |
| Destructive | "Archive this job? 47 candidate links stay readable; the job leaves the pipeline." | "Delete permanently?" |
| Pay | "HRAgents prepares payroll. It never pays. Review and run payroll in your bank or payroll provider." | "Payroll complete." |

Prefer reversible verbs; deletion needs typed confirmation, an export offer, and a receipt. Name the field and the fix.

## 9. Delete from the current UI

- Board / Queue / Chat tabs and the 10-workspace switcher.
- Raw UUIDs in labels, URLs, and toasts.
- "Bump progress +10%" and synthetic progress controls.
- Raw JSON / input blobs in Pay and Ops.
- Inline destructive icons in table rows.
- Hidden `/ops` page (fold into Settings ▸ Diagnostics).
- Dead links and placeholder notices ("Ask HR has no board").
- PWA prompts, mobile bottom bar, marketing footer, mobile-first layout.
- Duplicate Home/Approvals entry points; Today is the only inbox.
- Red/green scores and letter grades; ungated drag-to-reject.

## 10. Acceptance criteria

- [ ] Five surfaces + Settings; no Board/Queue/Chat tabs.
- [ ] No UUID or raw enum in any label, URL, or toast.
- [ ] Every list works keyboard-only, focus restored on return.
- [ ] Every action yields a receipt: actor, reason, time, audit ref.
- [ ] Today, decision, candidate, profile, run reachable in ≤2 actions.
- [ ] Empty, loading, error exist for every route; no dead end.
- [ ] "Never pays" on every Pay screen and export.
- [ ] Locale parity; no hardcoded English; Jakarta/IDR correct.
- [ ] `axe`: zero serious/critical per route and theme.
- [ ] 1024×700 usable; no mobile reflow.

**Visual QA**

- [ ] One accent button; status <5% of pixels; icon + label.
- [ ] Scale 12/14/16/20/24 only; 12px metadata; tabular numbers.
- [ ] 4px grid; no nested cards; one shadow maximum.
- [ ] Tables aligned, 32–40px rows, no scroll at 1280.
- [ ] Focus ring everywhere; tab order follows reading.
- [ ] Empty states actionable; errors keep input.
- [ ] Dark mode identical contrast; no stray hex.
- [ ] 200% zoom: nothing clipped or lost.
- [ ] Long names and Indonesian copy fit without truncation.
