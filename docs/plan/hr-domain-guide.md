# HR Domain Guide

**Version:** 0.1.0 · **Purpose:** a ground-up explanation of HR work for the HRAgents team —
so every workspace, agent, and gate is grounded in what HR actually does, not what
software people assume HR does.

**Accuracy note:** Indonesian labor specifics below are *structural overviews*. Rates,
caps, and thresholds change (Cipta Kerja amendments, annual tax/BPJS updates). Exact
current values are captured and verified from official sources (Kemnaker, BPJS, DJP)
when each module is implemented — Phase 8 of the master plan. Nothing here is legal
advice, and the product must never present it as such.

---

## 1. What HR is (for a small company)

In enterprises, HR is five departments: Talent Acquisition, HR Operations, Compensation &
Benefits, Learning & Development, and Employee Relations. In a 50–300 person Indonesian
SME, it is **one person** doing simplified versions of all five, plus office admin.

Their three simultaneous jobs:

1. **Fill and keep the team** — hire, onboard, retain.
2. **Keep the company legal** — contracts, BPJS, taxes, data protection, reporting.
3. **Keep the peace** — answer questions, resolve friction, run reviews, handle exits.

Everything in HRAgents maps to relieving job 1 (volume work), assisting job 2
(calculation, reminders, records), and supporting job 3 (drafting, tracking, Q&A).

---

## 2. The employee lifecycle

```
Hire ──────► Onboard ──────► Work ──────────────► Grow ──────► Leave
Sourcing     Contracts       Records              Reviews      Resignation/termination
Screening    Documents       Leave & attendance   Promotions   Final pay (pesangon)
Interviews   Setup           Payroll              PIPs         Asset return
Offer        Orientation     Policy Q&A           Training     Exit interview
```

| Stage | Workspace | The human moment | The agent work |
|---|---|---|---|
| Hire | Hiring | "I like this person" | Read, score, coordinate, draft |
| Onboard | Onboarding | "Welcome aboard" | Chase docs, checklist, schedule |
| Work | People / Leave / Payroll | "Here's your answer" | Records, math, Q&A, flags |
| Grow | Growth | "Here's your feedback" | Remind, collect, draft |
| Leave | Offboarding | "Thank you, good luck" | Checklist, schedule, tracker |

---

## 3. The functions, one by one

### 3.1 Recruitment (Talent Acquisition)

**The funnel:** sourcing → application → screening → interview(s) → offer → hire.
In practice: post on job portals (Jobstreet, Glints, Kalibrr, Dealls) and LinkedIn,
watch applications arrive through portals + email + WhatsApp, screen, coordinate
interviews across everyone's calendars, negotiate, prepare the offer.

**The pain:** screening volume (60+ CVs per role), coordination chaos, and silence —
candidates get no updates, and rejection is usually "no reply ever."

**Key artifacts:** CVs, portfolio links (GitHub, Behance, etc.), interview notes,
offer letter.

**Agents:** extract evidence, score deterministically, run async WhatsApp/email
conversations, schedule, draft feedback. **Humans:** interviews, judgment, the
hiring decision, the offer.

### 3.2 Onboarding

**What happens:** contract signing (see PKWT/PKWTT below), collecting identity and tax
documents (KTP, NPWP, bank account, BPJS numbers), account/equipment setup,
orientation, introductions, probation tracking.

**The pain:** chasing people for documents for weeks; forgotten checklist items; a new
hire's first day with no laptop.

**Agents:** checklist engine, document reminders + extraction/validation, scheduling.
**Humans:** welcome, contracts, anything signed.

### 3.3 Employee Records

**What it is:** the personnel file — identity data, contracts, education, emergency
contacts, salary history, leave balances, performance records. In many SMEs this is a
spreadsheet named `DATA KARYAWAN FINAL v3 (2).xlsx`.

**The pain:** it decays, duplicates, and goes stale; contract expiry sneaks up; nobody
knows who has which document.

**Agents:** structured records, expiry alerts, search, retention/erasure automation
(UU PDP). **Humans:** corrections, sensitive fields, decisions.

### 3.4 Time & Attendance

**What it is:** working hours, attendance (manual fingerprint exports, apps, or trust),
overtime (lembur), lateness, leave. Feeds payroll.

**Key rules (structure):** standard working time is 40 hours/week — 7h/day × 6 days or
8h/day × 5 days (UU Ketenagakerjaan No. 13/2003; Cipta Kerja amended enforcement).
Overtime is capped (indicatively 4h/day, 18h/week) and paid at premium rates (the first
overtime hour at 1.5× hourly wage, subsequent hours at 2×, with different treatment on
rest days and holidays). **Verify current formula (PP 35/2021) at implementation.**

**Agents:** import attendance files, compute totals, flag anomalies ("4× baseline
overtime"). **Humans:** approve corrections.

### 3.5 Leave (cuti & izin)

**Categories to support:**
- **Cuti tahunan** — annual leave: 12 working days after 12 months of service (minimum
  per UU 13/2003), plus long-service leave under separate rules (indicatively 2 months
  after 6–7 years, 3 months after 8+ years).
- **Cuti sakit** — sick leave: paid sick leave is governed by rules requiring medical
  certificates for longer periods; long-term illness has statutory protections.
- **Izin** — permission for personal matters (marriage, bereavement, religious
  obligations) — several are paid rights (e.g., marriage, immediate family bereavement).
- **Maternity/paternity** — maternity leave was expanded under Cipta Kerja
  (indicatively 3 months, extendable with medical certification); paternity leave
  (indicatively 2 days, extendable by agreement).
- **Public holidays** — national holidays plus joint leave (cuti bersama) set yearly.

**The pain:** balance math, accrual by hire date, overlapping requests, disputes about
"how many days do I have left."

**Agents:** balances, policy Q&A with citations, request routing. **Humans:** every
approval (usually the manager; HR administers).

### 3.6 Payroll (the most dangerous room)

**The pieces:**
- **Gross salary** = base + fixed allowances (transport, meal, housing…).
- **Additions:** overtime, bonuses, THR.
- **Deductions:** employee BPJS contributions, PPh 21 income tax, loans, absences.
- **Employer costs (not deducted):** employer BPJS shares — these are company expenses
  on top of salary.

**BPJS — two agencies:**
- **BPJS Kesehatan (health):** employer ~4% + employee ~1% of monthly wage, with a
  salary cap (civil servant/private caps updated periodically).
- **BPJS Ketenagakerjaan (employment):** four programs — JHT (old-age savings,
  employer ~3.7% + employee ~2%), JKK (work-accident, employer ~0.24–1.74% depending on
  risk class), JKM (death, employer ~0.3%), JP (pension, employer ~2% + employee ~1%,
  with a wage cap).
  **All percentages are indicative — verify current rates with BPJS at implementation.**

**PPh 21 (income tax on employment):** withheld monthly by the employer; the scheme was
simplified in 2024 (monthly effective rates — TER) with annual reconciliation in the
February–March filing window; formulas depend on PTKP status (marital/dependents).
**Verify with DJP rules at implementation.**

**THR (Tunjangan Hari Raya):** mandatory religious-holiday bonus. Employees with 12+
months of service get 1 month's wage; 1–11 months get a prorated amount (months/12 ×
1 month). Must be paid at least 7 days before the holiday (Permenaker 6/2016).
Employer violators face sanctions.

**Slip gaji:** payslip — itemized statement of earnings and deductions.

**The product rule:** HRAgents **prepares and verifies** — assembles inputs, computes
previews, flags anomalies, exports a review packet. **It never executes payments and
never generates bank instruction files.**

### 3.7 Performance (Growth)

**What it is:** review cycles (quarterly/annual), goals/OKRs, probation evaluations,
and PIPs (Performance Improvement Plans) for underperformance — which legally matter
(employers must document performance issues properly before termination).

**Agents:** cycle reminders, form collection, draft summaries (human-edited).
**Humans:** every rating, every conversation.

### 3.8 Offboarding

**Resignation path:** notice (30 days under UU 13/2003), handover, asset return, exit
interview, final pay, BPJS/deactivation admin, reference letter (paklaring).

**Final pay can include:** final month salary, unused leave encashment, **pesangon**
(severance) and **penghargaan masa kerja** (service award) where applicable, plus
regulatory compensation for PKWT completion. Severance rules are complex (depend on
reason, tenure, and contract type) — the product prepares estimates and checklists;
qualified humans and the company's advisors decide.

### 3.9 Employee Relations & Compliance

Day-to-day: answering questions (leave, BPJS, policies), mediating friction, warning
letters (SP1/SP2/SP3 — progressive sanctions structure), and compliance reporting
(WLKP — company employment report to Kemnaker; BPJS contributions timely;
UU PDP — data protection). Agents: knowledge with citations, reminders, records.
Humans: everything with legal weight.

---

## 4. Indonesian specifics you must know

### 4.1 Contract types

| Type | What it is | Key rules |
|---|---|---|
| **PKWTT** | Permanent (a.k.a. kontrak tetap) | Max 3-month probation allowed; full severance obligations |
| **PKWT** | Fixed term | Must be written, for a specific duration/project; **no probation**; maximum total ~5 years including extensions; requires **uang kompensasi** (compensation) when it ends; specific rules for transfer/termination |

### 4.2 Key numbers to verify at implementation (never ship guessed)

- BPJS rates and salary caps (annual updates).
- PPh 21 TER tables and PTKP amounts (DJP).
- Overtime premium formula (PP 35/2021).
- Minimum wage (UMR/UMP/UMK) — provincial/city yearly.
- Severance scale (PP 35/2021 tables).
- National holidays + cuti bersama (annual decree).
- THR timing (7 days before holiday).

### 4.3 Data protection (UU PDP 27/2022)

Employee and candidate data are personal data. Consent/lawful basis, purpose
limitation, retention, security, and data-subject rights (access, correction, erasure)
all apply. HR is the data controller's operator; the software must make compliance
easier, not harder. (Details: `skills/platform/compliance/knowledge/uu-pdp-summary.md`.)

---

## 5. Glossary (ID ↔ EN)

| Indonesian | English | Notes |
|---|---|---|
| Karyawan | Employee | |
| Pelamar | Applicant | |
| Rekrutmen | Recruitment | |
| Lowongan | Job vacancy | |
| Wawancara | Interview | |
| Penawaran | Offer | |
| PKWT / PKWTT | Fixed-term / Permanent contract | See §4.1 |
| Probasi / masa percobaan | Probation | PKWTT only |
| Onboarding | Onboarding | Often still English |
| Offboarding | Offboarding | |
| Cuti tahunan | Annual leave | |
| Cuti sakit | Sick leave | |
| Izin | Permission / leave for personal matters | |
| Cuti melahirkan | Maternity leave | |
| Lembur | Overtime | |
| Absensi | Attendance | |
| Gaji pokok | Base salary | |
| Tunjangan | Allowance | |
| Potongan | Deduction | |
| Slip gaji | Payslip | |
| THR | Religious holiday bonus | Tunjangan Hari Raya |
| Pesangon | Severance | |
| Penghargaan masa kerja | Service award | Part of final pay |
| Uang kompensasi | PKWT completion compensation | |
| BPJS | National social security | Kesehatan + Ketenagakerjaan |
| JHT | Old-age savings | Jaminan Hari Tua |
| JKK / JKM / JP | Work accident / death / pension | |
| PPh 21 | Employee income tax | |
| NPWP | Tax ID | |
| KTP | National ID card | |
| WLKP | Company employment report | Wajib Lapor Ketenagakerjaan |
| SP1/SP2/SP3 | Warning letters 1/2/3 | Progressive discipline |
| Paklaring | Reference letter | |
| Resign / pengunduran diri | Resignation | |
| PHK | Termination of employment | Pemutusan Hubungan Kerja |
| Kontrak | Contract | |
| Peraturan perusahaan | Company regulations | Often required at scale |
| UMP / UMK | Provincial / city minimum wage | |

---

## 6. A day in the life (and where HRAgents helps)

| Time | Rina does | Without HRAgents | With HRAgents |
|---|---|---|---|
| 08:30 | Opens laptop, checks inboxes | 3 inboxes, dread | Home shows exactly what needs her |
| 08:45 | Screens CVs | 60 CVs × 7-second scans | Board already ranked with evidence |
| 09:30 | WhatsApps candidates | Free-text chaos | Agents already collected availability |
| 10:30 | Chases onboarding documents | Sends reminders manually | Agents reminded; status visible |
| 11:30 | "How many leave days do I have?" ×5 | Repeat from memory | Ask HR answers with citations |
| 13:00 | Prepares payroll inputs | Spreadsheet + panic | Anomalies flagged; packet exported |
| 14:30 | Chases engineering lead feedback | Waits; decisions stall | Review queue makes the ask visible |
| 15:30 | Contracts expiring? | Hopes the spreadsheet is right | Watching list shows 30-day expiries |
| 16:30 | Rejections pending | Silent, guilt, or generic copy-paste | Sign-off queue → honest feedback in 2 clicks |
| 17:00 | "What did I forget?" | Anxiety | Audit log + cleared queues |

---

## 7. How to use this guide

- Building a workspace? Read its §3 subsection first; the board must match the real
  artifact (a leave calendar behaves like leave, not like a todo list).
- Writing a skill? The vocabulary in §5 and the gates in §3 are the source of truth.
- Claiming compliance? Check §4.2 — if the number is not verified from the official
  source, it does not ship.
- Selling to a company? The lifecycle in §2 and the pain column in §6 are the pitch.
