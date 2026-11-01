# 00 — Product Scope

**Status:** locked for the desktop edition · **Supersedes:** the web-first assumption in
`docs/plan/product-concept.md`

---

## 1. What this product is

HRAgents Desktop is the **HR department of one, in a box**.

One HR person — or a two-to-three person HR team — runs hiring, onboarding, people
records, leave, payroll preparation, growth administration, offboarding, and
compliance from a single local application. The app does the repetitive work:
reading CVs, chasing documents, assembling payroll, drafting messages, calculating
statutory figures, reminding people, and writing the audit trail. The HR operator
makes every consequential decision.

It is **not** a company-wide HRIS. There are no employee logins, manager logins,
finance logins, or candidate portals in this edition. If the company needs those,
that is the future server edition.

> **The product promise:** the HR operator gets a team without hiring one, and every
> decision is auditable.

---

## 2. The user

| Attribute | Decision |
|---|---|
| Primary user | HR generalist / HR manager at an Indonesian SME |
| Company size | 10–250 employees |
| HR team size | 1–3 people |
| Technical comfort | Excel/Canva-level; not a developer |
| Device | Windows laptop or desktop first; macOS second |
| Network | Intermittent; LLM/email may be online, core work must not require a server |
| Data sensitivity | High: payroll, identity documents, leave reasons, performance notes |
| Language | Bahasa Indonesia and English |

### Multiple HR operators

A company may have more than one HR person. They all share **one role**,
`hr_operator`, and all have the same permissions. The audit chain records **which**
HR person did what. There is no role matrix to configure.

This is deliberate: it preserves the named-human guarantee without building RBAC.

### One install, one company, one machine

A desktop install is a single-company database on a single machine. Multiple HR
operators can sign in on that machine with separate local accounts. If two HR people
work on different laptops and need **live shared data**, that is the server edition,
not this one. The desktop edition supports backup/restore and export, not real-time
multi-machine sync.

---

## 3. Login — yes, and what it means

The app requires a local login because:

1. It protects payroll, identity documents, and candidate PII on a shared laptop.
2. It binds every audit entry to a named person, not a machine.
3. It enables re-authentication before payroll sign-off, erasure, or a gated
   rejection override.
4. It supports app lock on idle/sleep and a recovery path.

It is **not** a server account, email/password reset, SSO, or multi-tenant identity.
The first-run wizard creates the first operator and the company. Additional operators
can be added locally by an existing operator. There is no "admin" role; every
operator is HR.

Login and session details are in [`06-auth-security.md`](06-auth-security.md).

---

## 4. What the HR operator actually does

The feature set is organized by the HR operator's jobs, not by departments:

| Job to be done | Product surface | What the app removes from HR's plate |
|---|---|---|
| "Who needs me today?" | **Today** | Collects every decision, task, reminder, and expiring record into one inbox |
| "Hire this person" | **Hire** | CV intake, extraction, scoring, evidence, scheduling, offers, rejection/offer drafts, feedback |
| "Get this person started" | **People → Onboarding** | Checklists, document requests, contract prep, reminders, progress |
| "Keep the records straight" | **People** | Directory, contracts, documents, expiry alerts, org chart |
| "Who is off, and who is owed what?" | **People → Leave** | Balances, requests on behalf, approvals, team calendar, holidays |
| "Run payroll without guessing" | **Pay** | Verified rate tables, inputs, computation, anomalies, approval, XLSX packet |
| "Review performance without a spreadsheet" | **People → Growth** | Cycles, forms sent/collected, summaries, goals, reminders |
| "Exit this person cleanly" | **People → Offboarding** | Checklist, assets, clearance, handover, final pay, sign-off |
| "Can I prove what happened?" | **Settings → Audit / Compliance** | Hash-chained log, consent, retention, erasure, breach, rate verification |
| "What is our policy?" | **Ask** | Cited policy answers with handoff to the relevant record |

---

## 5. Five surfaces, one settings area

```
Today        — decisions, deadlines, expiring records, agent activity
Hire         — pipeline, candidates, jobs, import, interviews, offers
People       — directory, person profile, onboarding, leave, growth, offboarding
Pay          — payroll runs, compensation, rates, compliance
Ask          — policy chat with citations and handoffs
Settings     — company, operators, providers, backup, updates, audit
```

The old 10-workspace × Board/Queue/Chat model is removed. Cross-links replace the
rooms: every item opens the exact record, and every record has a "next action" bar.

---

## 6. In scope

### Hiring

- Job creation and editing, job families, weights, rubrics.
- Single and batch candidate intake (CSV, XLSX, PDF, DOCX, text).
- CV/document extraction, evidence references, deterministic scoring, σ, flags.
- Candidate profile, contact details, consent, links, documents.
- Pipeline stages, ranked cards, waiting time, priority.
- Human review: CV and evidence side by side, override with reason, audit receipt.
- Scheduling proposals, availability, confirmation, ICS export.
- Offers: revisions, approval, message, acceptance/decline, expiry.
- Candidate communications: rejection/offer drafts, preview, send/mark sent,
  history, replies via IMAP.
- Candidate feedback report/PDF.
- Gated rejection above the merit floor; no auto-rejection.

### People

- Employee directory, org units, org chart, headcount.
- Person profile: contact, employment, compensation, documents, contracts, leave,
  payroll history, onboarding/offboarding, timeline.
- Employee create/edit/transition; payroll profile (dependents, JKK class, PTKP,
  bank details, BPJS membership).
- Contracts: create, activate, terminate, expiry, renewal reminders.
- Document vault: upload, preview, download, verify/reject, expiry, retention.
- Document requests: create, approve, chase, link to vault.

### Leave

- Leave policies, accrual, balances, adjustments.
- HR records leave on behalf of an employee.
- HR decides leave requests (as the named human).
- Team calendar, holidays, half-days, attachments.
- Cancellation/withdrawal with reason.

### Payroll

- Compensation records per employee.
- Monthly, THR, adjustment, and final-settlement runs.
- Per-run inputs: base salary, allowances, overtime, absence, bonus, deductions,
  loans, service months, notes.
- Verified statutory rate tables: BPJS, PPh 21 PTKP/TER, overtime, THR, minimum wage.
- Compute, blocking/advisory anomalies, immutable runs, supersede, cancel.
- Submit, approve (HR), export XLSX review packet, payslip view.
- Never executes payments.

### Growth

- Review cycles, assignments, rating scales, forms.
- HR sends forms to reviewers via email/PDF/CSV; imports responses; no reviewer login.
- Summaries: draft, edit, finalize with author.
- Goals: create, activate, progress, complete, cancel, overdue.
- Reminders and collection status.

### Offboarding

- Templates, plans, steps, assets, clearance, exit interview, handover.
- Final pay run and finalize employee exit, with sign-off.

### Compliance

- Consent registry; withdrawal enforced before processing.
- Retention records and holds; purge with preview and typed confirmation.
- Erasure requests, approval, execution, journal.
- Breach incidents and containment steps.
- Audit chain: browse, filter, verify, export.
- Rate-table verification with source note and effective dates.
- Compliance calendar.

### Ask HR

- Policy chat with citations, tools, workspace-aware routing, handoffs.
- Conversation history persisted locally.
- Suggested questions, source snippets, "create task/decision" handoff.

### Platform

- Local login, app lock, re-auth for consequential actions.
- Global search (people, candidates, jobs, documents, audit, decisions).
- Local notifications/reminders.
- Backup/restore, export/import, update, diagnostics.
- English + Bahasa Indonesia.
- One company per install.

---

## 7. Out of scope for this edition

| Removed | Why |
|---|---|
| Employee self-service / employee login | The product is the HR cockpit; employee-facing workflows are a server edition |
| Manager/finance/recruiter/admin roles | One HR role; named-human audit still records the person |
| Candidate portal | Communication happens through HR's email/WhatsApp; no candidate account |
| Multi-tenant / RLS / SaaS billing | One company per install; tenant scoping is unnecessary |
| Docker / Postgres / Redis / MinIO / Mailpit | Local SQLite and in-process jobs; no infrastructure |
| PWA / push / service worker | Desktop app, not mobile |
| Inbound webhooks (WhatsApp Cloud, Telegram, Resend) | Desktop has no public URL; use IMAP polling and `wa.me` links |
| MCP marketplace / connector catalog | Developer feature; not HR's job |
| Provider marketplace | A small, opinionated provider set with a local settings screen |
| Paper/research pages in the product | Keep the paper as a publication, not a product surface |
| Storybook | Not part of the shipped app |
| Demo-only controls ("Bump progress +10%") | Delete; every control must be a real HR action |

A future **server edition** can reuse the Rust core and add a Postgres/Axum adapter,
multi-user auth, webhooks, and a candidate/employee portal. The desktop edition must
not carry that complexity.

---

## 8. Scope rules for every feature

A feature enters this edition only if it passes all four:

1. **It removes repetitive work from HR.** Extraction, calculation, drafting,
   chasing, reminding, assembling, summarizing.
2. **It ends in an HR decision or an HR-owned record.** No autonomous consequential
   action.
3. **It works offline or degrades gracefully.** Core records, payroll, and audit must
   work without a network.
4. **It is auditable.** The actor, time, reason, and payload are recorded.

If a feature needs an employee/manager login, a public webhook, or multi-company
tenancy, it belongs to the server edition.

---

## 9. Success metrics

| Metric | Target |
|---|---|
| Time from install to first useful record | < 5 minutes |
| Time from install to first evaluated candidate | < 10 minutes |
| Clicks from Today to a decision | 1 |
| Time to assemble a monthly payroll run | < 15 minutes for 50 employees |
| Time to find a person/document/candidate | < 5 seconds |
| Audit reconstruction of any decision | < 1 minute |
| Crash-free sessions | > 99.5% |
| Backup success | 100% of scheduled backups verified |
| User-reported "where do I click?" issues | 0 in pilot |

---

## 10. Non-negotiable safety properties

- No payment execution.
- No auto-rejection above the merit floor.
- No statutory rate is used until an HR operator verifies it against a source.
- No consequential action without an authenticated HR operator.
- No audit entry without an actor and a payload hash.
- No candidate/employee PII in logs, crash reports, or telemetry.
- No background agent can approve, reject, erase, or export on its own.

These survive the rewrite unchanged.
