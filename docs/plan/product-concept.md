# Product Concept — HRAgents

**Version:** 0.1.0 · **Status:** locked direction
**Audience:** the author (build decisions), contributors, and later the landing page.

---

## 1. Positioning

> **A virtual HR team for the HR department of one.**

An Indonesian SME with 50–300 people typically has **one HR generalist** (sometimes two)
doing ten jobs: hiring, onboarding, records, leave, payroll coordination, performance,
offboarding, policy questions, compliance. No human does ten jobs well. HRAgents gives
that person a team of agents that handle the reading, chasing, calculating, and drafting —
while the human keeps every decision that matters.

**What it is not:** it does not replace HR, it does not decide who gets hired or fired,
and it never executes money. It is a productivity multiplier with hard human gates at every
consequential step.

### Why this is trustworthy

The design follows directly from the evidence base (`docs/research/literature-review.md`):

- Legacy screening is broken: 7.4-second scans, persistent bias, silent rejections.
- The obvious fix (learn from history) fails — Amazon 2018.
- The correct architecture: **agents extract and communicate; deterministic code decides;
  humans gate every rejection.**

This is the product's integrity story: every score is reproducible, every decision is
auditable, and no candidate is ever silently rejected.

---

## 2. Persona

**"Rina" — the HR department of one.**

- 28–40 years old, generalist, at a 80–250 person Indonesian company (tech, agency,
  manufacturing, retail).
- Works from a laptop + phone; everything happens in Google Workspace, WhatsApp, and
  spreadsheets.
- Interrupted every 20 minutes; keeps a running list of "things I haven't gotten to."
- Fears: forgetting something important, missing a good candidate, making a payroll
  mistake, being blamed for something she can't prove she handled correctly.
- Not technical beyond Excel and Canva; will not read documentation unless the product
  itself teaches her.

**Product promise to Rina:** open the app, see exactly what needs you, clear it, and know
that everything else is being watched. Nothing falls through the cracks, and every
decisions has a record.

---

## 3. The division of labor

| The agent team does | The HR person does |
|---|---|
| Read CVs, repos, documents at volume | Judgment calls |
| Score evidence deterministically | Approvals and accountability |
| Chase documents, reminders, scheduling | Relationships (candidates, employees, managers, bosses) |
| Calculate (leave balances, payroll inputs, expiry dates) | Final say on money and legal matters |
| Draft (feedback, job posts, checklists, summaries) | Sensitive conversations |
| Watch (expiries, SLAs, anomalies, flags) | Deciding what "good" looks like for this company |

The rule: **agents never decide anything about a person's employment or money.**

---

## 4. The workspace map

Eight user-facing workspaces. Each is a self-contained room: its own board, its own
decision queue, its own scoped agents and knowledge.

| # | Workspace | What the HR person does there | What agents do | What humans gate |
|---|---|---|---|---|
| 1 | **Hiring** | Review candidates, schedule, decide | Extract, score, coordinate async, draft feedback | Every rejection (policy-gated), every offer |
| 2 | **Onboarding** | Welcome new hires, follow up on documents | Checklists, reminders, document extraction/validation, scheduling | Contract terms, anything signed |
| 3 | **People** | Look up employee info, track records | Search, expiry alerts, retention/erasure compliance | Data corrections, salary fields |
| 4 | **Leave** | Approve requests, answer policy questions | Balance math, policy Q&A with citations, routing | Every approval |
| 5 | **Payroll** | Run the month's payroll inputs | Assemble data, calculate inputs, flag anomalies, export review packet | **Everything** — no payment ever executed |
| 6 | **Growth** | Run review cycles, coach managers | Reminders, form collection, summary drafts | Every review outcome |
| 7 | **Offboarding** | Process exits, final pay coordination | Checklists, asset return tracking, exit interview scheduling | Final pay, anything legal |
| 8 | **Ask HR** (front door) | Ask anything, route to a workspace | Intent classification, policy Q&A with citations, cross-workspace handoff | Anything consequential; router never decides |

Cross-cutting: **Compliance** surfaces through each workspace (consent, retention, audit),
and in the audit viewer.

### Wave order (build order — all departments are in scope)

| Wave | Workspaces | Status |
|---|---|---|
| 1 | Hiring (deep), Ask HR, light Onboarding | Building |
| 2 | People, Leave | Engines built |
| 3 | Payroll prep, Growth, Offboarding, full Compliance | Engines built |

---

## 5. Dashboard UX

### 5.1 Home is "what needs you"

Not charts. Not vanity metrics. The #1 anxiety is *"what am I forgetting?"* — so home
answers exactly that.

```
┌──────────────────┬──────────────────────────────────────────────────────────┐
│  HRAgents        │  Ask anything… (policy, people, status)                  │
│                  ├──────────────────────────────────────────────────────────┤
│  ● Home          │                                                          │
│  ○ Hiring        │  NEEDS YOU TODAY                                         │
│  ○ Onboarding    │                                                          │
│  ○ People        │  ▲ 2 candidate rejections awaiting your sign-off         │
│  ○ Leave         │  ▲ 1 payroll anomaly flagged for review                  │
│  ○ Payroll       │  ▲ 1 onboarding: contract signature outstanding          │
│  ○ Growth        │                                                          │
│  ○ Offboarding   │  WATCHING (no action yet)                                │
│                  │                                                          │
│  ──────────────  │  • 3 contracts expiring within 30 days                   │
│  Audit log       │  • 5 candidates replied — scheduling in progress         │
│  Settings        │  • 2 onboarding documents still missing                  │
│                  │  • Payroll run closes in 4 days                          │
└──────────────────┴──────────────────────────────────────────────────────────┘
```

Rules:
- **"Needs you"** = decisions gated on a human (rejections, approvals, anomalies).
  Sorted by deadline, then impact. Every item links to its workspace queue.
- **"Watching"** = things agents are handling or monitoring. No action required; here
  so nothing is invisible.
- Zero items in "Needs you" is a legitimate, celebrated state — an empty inbox feeling.

### 5.2 Three rooms per workspace

Every workspace has the same anatomy:

1. **Board** — the work object (candidate pipeline, employee list, leave calendar,
   payroll run, onboarding checklist).
2. **Queue** — decisions waiting on the human (approvals, flags, expiries).
3. **Chat** — ask this workspace's agents about this workspace's domain only.
   Hiring chat sees recruiting knowledge; Payroll chat sees payroll knowledge and
   **never** candidate data.

This is your "workspace = subagent" idea, made concrete. It is both UX and security:
context isolation is enforced, not suggested.

### 5.3 Navigation model

- **Direct entry:** HR clicks a workspace and works deterministically inside it. No
  routing guesswork.
- **Front door:** HR asks the top bar something ("screen these CVs and set up
  interviews"). The router classifies intent, picks the workspace, and shows its
  proposal — but it never executes consequential actions itself.
- **Mobile:** workspace switcher becomes a bottom bar; queues and chat are fully usable
  from the phone; approvals take two taps.

---

## 6. Wireframes

### 6.1 Hiring board (kanban)

```
┌─ Hiring ─────────────────────────────────────────────── [+ Add candidates] ─┐
│ Backend Engineer • 47 candidates • 12 need review                            │
│                                                                              │
│  RECEIVED (18)     SCREENED (12)    INTERVIEW (5)      OFFER (2)            │
│ ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐        │
│ │ ▢▢▢▢▢ 0.91 │    │ ▢▢▢▢▢ 0.87 │    │ Mon 10:00  │    │ ▢▢▢▢▢ 0.93 │        │
│ │ ▢▢▢▢▢ 0.88 │    │ ▢▢▢▢▢ 0.84 │    │ Tue 14:00  │    │ awaiting   │        │
│ │ ▢▢▢▢▢ 0.82 │    │ ▲ needs    │    │ confirmed  │    │ signature  │        │
│ │ ▲ flag     │    │   sign-off │    │            │    │            │        │
│ └────────────┘    └────────────┘    └────────────┘    └────────────┘        │
└──────────────────────────────────────────────────────────────────────────────┘
```

Cards show score bars (grayscale), flags (amber dot), and next action. Drag between
columns triggers the appropriate gated flow — dragging to "rejected" opens the sign-off
queue, it does not send anything.

### 6.2 Candidate detail

```
┌─ Budi Santoso ─────────────────────── Backend Engineer ────── [Advance ▸] ─┐
│                                                                             │
│  SCORE BREAKDOWN                       EVIDENCE                             │
│  Technical depth      ████████░░ 0.82   • 6 yrs experience (resume §Exp)   │
│  Stack alignment      █████████░ 0.91   • Python/FastAPI/Postgres           │
│  Systems literacy     ███████░░░ 0.74     (github.com/… @ a3f2c1)          │
│  Certifications       ██████████ 1.00   • AWS SA cert verified (registry)  │
│                                                                             │
│  FLAGS: none          σ 0.03 ✓ auto-schedule eligible                       │
│  ─────────────────────────────────────────────────────────────────────────  │
│  TIMELINE   received → extracted → scored → queued for scheduling           │
└─────────────────────────────────────────────────────────────────────────────┘
```

Every number is clickable → shows the formula, weights, and source evidence. No hidden
ranking (hard rule).

### 6.3 Review queue (the HITL room)

```
┌─ Review queue — 3 items ────────────────────────────────────────────────────┐
│                                                                             │
│  ⚠ REJECTION SIGN-OFF                    0.70 ≤ S < 0.85                    │
│    Siti Rahma — Backend Engineer         S_tech 0.78 · σ 0.02 · no flags   │
│    "Rejection requires your signature."  [ View breakdown ] [ Sign ▸ ]     │
│                                                                             │
│  ⚠ ANOMALY                                date overlap detected             │
│    Andi Wijaya — AI Engineer             S_tech 0.88 · σ 0.01              │
│    [ View evidence ] [ Request info from candidate ▸ ]                     │
│                                                                             │
│  ⚠ CALENDAR                               only 1 mutual slot                │
│    Dewi Lestari — Backend Engineer       [ Propose slots ▸ ]               │
└─────────────────────────────────────────────────────────────────────────────┘
```

Sign-off dialog requires a reason code + optional notes; the signature lands in the
hash-chained audit log; the candidate-facing message previews before sending.

### 6.4 Payroll prep (wave 3)

```
┌─ Payroll — March 2026 ──────────────────────── Close in 4 days ────────────┐
│                                                                             │
│  38 employees · 3 changes since last run · 2 anomalies                     │
│                                                                             │
│  ⚠ Anomaly: overtime 4× baseline — Rudi (Production)                       │
│      Check attendance import; approve or correct → [ Review ▸ ]            │
│                                                                             │
│  PREVIEW   Gross payroll        Rp xxx,xxx,xxx                             │
│            BPJS + PPh 21 inputs Rp xx,xxx,xxx  (structure per current regs)│
│            Net preview          Rp xxx,xxx,xxx                             │
│                                                                             │
│  [ Export review packet (XLSX) ]   — no payments are executed by HRAgents  │
└─────────────────────────────────────────────────────────────────────────────┘
```

The export is the deliverable: HR (or their payroll provider/accountant) reviews and
executes externally. HRAgents never touches bank files.

---

## 7. Design system (locked)

### 7.1 Monochrome cool gray, light default

Color is **signal**, not decoration. A calm grayscale interface means a single amber dot
screams "you have something to do."

**Neutral ramp (light):**

| Token | Hex | Use |
|---|---|---|
| `bg` | `#FFFFFF` | Page background |
| `bg-subtle` | `#F8F9FA` | Sidebar, table stripes |
| `border` | `#E9ECEF` | Dividers, card borders |
| `border-strong` | `#DEE2E6` | Inputs, focus outlines (with accent) |
| `text-muted` | `#868E96` | Secondary text, metadata |
| `text` | `#343A40` | Body text |
| `text-strong` | `#212529` | Headings, numbers |

**Accent (one):** `#2563EB` — interactive elements only (primary button, link, focus
ring, active nav). In dark mode: `#3B82F6`.

**Status colors (≤5% of pixels, never the only signal):**

| State | Color | Icon required |
|---|---|---|
| Awaiting human | `#D97706` amber | ▲ |
| Overdue / error | `#DC2626` red | ● |
| Verified / done | `#16A34A` green | ✓ |

**Dark mode:** swap the neutral ramp (page `#16191D`, borders `#2B2F36`, text
`#E9ECEF`); accent and status colors stay. This is a token swap, not a redesign.

The derived dark shades are locked too: `bg-subtle` `#1D2126`, `border-strong`
`#3A4048`, `text-muted` `#8A9199`, `text` `#CED4DA` (dark accent `#3B82F6`).
Implemented in `web/src/styles/theme.css`, the only file allowed to contain hex
values (enforced by `theme.guard.test.ts`).

### 7.2 Typography

- **UI:** Inter (or system stack) — weights 400/500/600 only.
- **Numbers/IDs:** JetBrains Mono for scores, currencies, IDs (tabular alignment).
- **Scale:** 12 · 13 · 14 (body) · 16 (section) · 20 · 24 · 30 (page title).
- Hierarchy comes from weight/size/spacing — not hue.

### 7.3 Density and components

- 4px spacing base: 4 / 8 / 12 / 16 / 24 / 32 / 48.
- Radius: 6px controls, 10px cards. Shadows: one, subtle; borders do the work.
- Compact tables (32–36px rows) — HR tools are data-dense.
- Component set: shadcn/ui themed to these tokens (button, input, table, dialog, toast,
  tabs, badge, progress bar for scores, command palette for search).
- Score bars use the gray ramp; the flagged score uses the one status color.

### 7.4 Accessibility

- WCAG AA (4.5:1) for body text; never color-only status (icon + label always).
- Visible focus rings (accent), full keyboard navigation, reduced-motion support.
- Mobile-first: queues, approvals, and chat are first-class on a 390px viewport.

---

## 8. Hard product rules (never ship against these)

1. **No money movement.** Payroll workspace prepares; humans execute externally.
2. **No auto-rejection with flags present.** Uncertainty escalates to a human.
3. **No rejection above the merit floor without a named human signature.**
4. **No hidden ranking.** Every score opens its formula, weights, and evidence.
5. **No anonymous overrides.** Names and roles are recorded.
6. **No silent candidates.** Every path ends in a communicated outcome within SLA.
7. **No cross-workspace data leakage.** Payroll chat cannot see candidates; hiring chat
   cannot see salaries.
8. **No training on historical hiring outcomes.**

---

## 9. The five-minute demo (the "yes" moment)

| Time | Screen | Beat |
|---|---|---|
| 0:00 | Home | "This is your morning: two rejections need your signature, one payroll anomaly, three contracts expiring. Nothing hidden." |
| 0:30 | Hiring | Drag 50 CVs in. Watch the board fill. "Agents read all 50 in full — not 7 seconds each." |
| 1:30 | Candidate detail | Open one. Score breakdown, every number citing evidence. "This is reproducible. Same inputs, same score." |
| 2:30 | Review queue | Sign one rejection (reason code → signature → feedback preview). Show the audit entry appear. "No one gets rejected silently. Ever." |
| 3:30 | Ask HR | "How many leave days for a new employee?" → cited answer from policy docs. |
| 4:00 | Payroll | Show the anomaly flag + review packet export. "It prepares; you approve; it never pays." |
| 4:30 | Close | "Everything you saw is logged and explainable. It runs on your server if you want. It's free." |

---

## 10. Open items (feed into Phase 6/10)

- Landing page narrative mirrors §1 + §9 (Next.js, SEO, hire-me page).
- Onboarding workspace scope for Wave 1: checklist + document collection only.
- Workspace switcher ordering by usage frequency, configurable later.
