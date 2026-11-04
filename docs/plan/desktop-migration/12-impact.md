# 12 — Impact

**Status:** draft for the desktop edition · **Related:** [`00-product-scope.md`](00-product-scope.md), [`09-sequence.md`](09-sequence.md)

---

## 1. The position

> **HRAgents is the audit-grade HR cockpit for the HR department of one.**
> It reads, calculates, drafts, and chases — so one HR person can run hiring,
> people, payroll preparation, and compliance without a team or a spreadsheet.
> It runs on the HR person's laptop. Company data stays there.

Not "a virtual HR team for ten departments."
Not "an AI that decides who to hire."
Not "a company-wide HRIS."

The narrower position is stronger because it matches what the product actually does
well: extraction, calculation, drafting, reminders, records, and an audit trail —
with an HR human in control.

---

## 2. Who feels the impact

| Person | Before | After |
|---|---|---|
| HR generalist | 10–20 browser tabs, WhatsApp, Excel, repeated typing, forgotten follow-ups | One Today inbox, one candidate case file, one payroll run, one audit trail |
| HR manager | Cannot prove why a rejection happened or who approved payroll | Every decision has a receipt; every rate has a source; every run is frozen |
| Owner / finance | Payroll assembled from spreadsheets, errors found late | Verified rate tables, anomalies before sign-off, XLSX review packet |
| Candidate | Slow or no response; opaque rejection | Faster communication; evidence-based feedback; no auto-rejection |
| Auditor / regulator | Reconstructing decisions from email | One hash-chained log, exportable and verifiable |

The product is not trying to replace HR. It removes the repetitive 60% so HR can do
the judgment work.

---

## 3. The demo that must land in five minutes

A fresh install, one demo company, no cloud keys, no Docker.

1. **Login** as the HR operator; the app opens on Today.
2. **Hire:** import one CV; the candidate appears with a name, not a UUID.
3. Open the **candidate case file**: CV on the left, evidence and score on the right.
4. Trigger a **gated rejection**: the app asks for a reason and sign-off; the audit
   receipt appears.
5. **People:** add an employee, start onboarding, see the checklist and the document
   request.
6. **Pay:** open a payroll run, see verified rates, compute, review one anomaly,
   approve, export the packet.
7. **Settings → Audit:** verify the chain; the whole story is there.
8. **Ask:** ask "how many annual leave days does Ayu have left?" and get a cited
   answer with a link to the record.

If a step needs a terminal, a Docker command, an API key, or a UUID, the demo is not
finished.

---

## 4. Metrics that matter

### Product impact

| Metric | Baseline | Target |
|---|---|---|
| Time to shortlist a candidate | hours across tabs | < 10 minutes |
| Time to assemble a monthly payroll (50 employees) | 1–2 days | < 15 minutes |
| Time to answer a policy question | minutes of searching | < 30 seconds with citation |
| Time to reconstruct a decision | email archaeology | < 1 minute |
| Forgotten follow-ups per hire | several | 0 (Today + reminders) |
| Rejections without a documented reason | unknown | 0 above the merit floor |

### Engineering impact

| Metric | Target |
|---|---|
| Cold start | < 1.5 s |
| Idle memory | < 150 MB |
| Installer | < 35 MB |
| Payroll 1,000 lines | < 2 s |
| Crash-free sessions | > 99.5% |
| Backup verification | 100% |
| Audit chain verification after restart | always passes |

### Adoption impact

| Metric | Target |
|---|---|
| Install → first record | < 5 minutes |
| Install → first evaluated candidate | < 10 minutes |
| Users needing a terminal | 0 |
| Support tickets about "where do I click?" | 0 in pilot |
| Pilot companies | 2 |
| Pilot duration | 6 weeks |

---

## 5. What is different from a generic ATS or HRIS

Generic tools store records and move cards. HRAgents adds:

1. **Evidence-linked scoring.** Every score cites the CV/project/document excerpt
   that produced it; a human can open the source and disagree.
2. **A real named-human gate.** Rejections above the merit floor require an
   authenticated HR operator and a reason; the audit chain records both.
3. **Verified payroll inputs.** Statutory rates are operator-maintained, source-
   verified, effective-dated, and unusable until verified.
4. **A reconstructible audit chain.** Not a log file; a hash chain with actor,
   provenance, payload, and verification.
5. **Local-first privacy.** The company's HR data is a local encrypted database, not
   a SaaS tenant.

The first two are rare. The third is local and high-pain. The fourth is the trust
layer. The fifth is the desktop advantage.

---

## 6. Business and distribution

- **Open source (Apache-2.0).** Free to self-install.
- **Paid integration/setup.** Install, configure email/WhatsApp/LLM, import data,
  train the HR team.
- **No SaaS billing, no license gating.**
- **Desktop installer is the onboarding.** The paid service is “we set it up with
  you,” not “we host it.”
- **Server edition later** only if real demand for manager/employee access appears.

The desktop app makes the business model coherent: a non-technical HR person can
install it, and the author can still sell setup and training.

---

## 7. What not to claim

- Do not claim a "virtual HR team" of ten departments. It is an HR cockpit with
  agents for extraction, drafting, calculation, and policy Q&A.
- Do not claim "same input, same score" without the caveat that extraction is
  probabilistic; the deterministic scorer is stable given the same structured
  evidence, and σ exists because extraction varies.
- Do not claim production fairness validation. The evals are synthetic; a pilot is
  needed.
- Do not claim “AI decides.” The product's value is that AI does **not** decide.
- Do not claim a five-minute install until the signed installer and demo are tested
  with a non-technical user.

---

## 8. Pilot plan

**Recruit 1–2 Indonesian SMEs** with 30–150 employees and a 1–2 person HR function.

**Before:** observe one hiring cycle and one payroll cycle; record time, tools, and
failure points.

**During (6 weeks):** install on the HR laptop; import 20–50 employees; run one
hiring cycle and one payroll cycle; use Today and Ask daily.

**After:** measure the metrics above; interview the HR operator; collect the top five
friction points; decide whether to continue, narrow, or stop.

**Do not** run a pilot without a signed installer, a backup/restore test, and a
support channel.

---

## 9. Release strategy

| Stage | Audience | Gate |
|---|---|---|
| Internal alpha | author + one friendly HR user | Five journeys pass on Windows; backup/restore |
| Private beta | 2 pilot companies | Signed installer; audit verification; payroll packet reviewed by an accountant |
| Public beta | open source users | Docs, demo company, crash diagnostics, update channel |
| 1.0 | production | External security review; pilot evidence; migration/export path |

Windows first. macOS after the Windows installer and updater are stable. Linux is a
nice-to-have, not a launch blocker.

---

## 10. The one-sentence test

If a stranger asks what this is, the answer should be:

> "It's a desktop app that does the repetitive HR work for a one-person HR
> department — hiring, onboarding, payroll prep, and compliance — and gives every
> decision an audit trail. Your data stays on your laptop."

If the answer starts with "AI agents" or "ten departments," the positioning is still
too broad.
