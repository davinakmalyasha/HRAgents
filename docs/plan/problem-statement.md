# The Problem Statement

**Version:** 0.1.0 · **Status:** draft for discussion
**Scope:** systemic — described from documented patterns, no individual or company is named.

---

## 1. The one-sentence problem

> Technical hiring in Indonesian SMEs is bottlenecked by a **single overloaded HR person**
> performing **unstructured, unauditable screening** under **severe time constraints** — a
> combination that systematically produces arbitrary outcomes, silent rejections, and avoidable
> bias, and that no amount of effort by that person can fix.

The problem is not that HR people are lazy or incompetent. The problem is **the structure they
operate inside**. One person cannot do deep technical evaluation at volume, and the tools they are
given were built for a different world.

---

## 2. The people affected

### 2.1 The solo HR person

A generalist running recruitment, onboarding, payroll coordination, and policy questions
simultaneously. Their day:

| Time | What happens | What breaks |
|---|---|---|
| 09:00 | Open job portal + email + WhatsApp | Three inboxes, no unified pipeline |
| 09:30 | Screen 60 CVs for a backend role | 7.4-second reads (Ladders, `ladders2018eyetracking`); keyword matching |
| 11:00 | WhatsApp candidates for interview slots | Free-text scheduling chaos |
| 13:00 | Chase the engineering lead for feedback | Decisions stall for days |
| 15:00 | Prepare payroll inputs / onboarding docs | Context switching, errors |
| 17:00 | Answer "how much leave do I have?" × 6 | Repeats the same answer from memory |
| Never | Send rejection feedback | Overwhelmed; ghosting becomes the default |

**The math is impossible:** 60 CVs × even 3 minutes of *fair* evaluation = 3 hours/day on screening
alone. The 7.4-second scan is not negligence — it is triage under an impossible workload.

### 2.2 The candidate

- No acknowledgment, no status, no feedback, no timeline
- Rejected by keyword absence rather than capability evidence
- Interviewed by a process that did not actually read their work (repos, publications, certifications)
- Exposed to discrimination at the exact moment documented by the audit studies
  (`bertrand2004emily`; `quillian2017meta`) — the initial screening decision
- Loses trust in the employer brand and in job search generally

### 2.3 The company

- **Cost:** every unfilled role burns payroll capacity and delays delivery; every bad hire costs
  multiples of salary to unwind
- **Lost talent:** strong engineers rejected for formatting, keywords, or pedigree — a measured,
  persistent failure mode, not a fear
- **Legal exposure:** candidate data processed without consent frameworks (UU PDP No. 27/2022),
  rejection decisions with no audit trail, no explanation capability
- **Reputation:** ghosting is remembered; candidates talk; the employer brand pays

---

## 3. Root causes (structural, not personal)

### R1 — Attention physics
A human initially evaluates a résumé in ~7.4 seconds and is optimized for *scanning*, not
*assessment*. Dense technical evidence (architecture work, open-source contributions, complexity of
shipped systems) cannot surface in that window. Formatting beats substance.

### R2 — Encoding mismatch
The signals that predict engineering success live in artifacts: repositories, commit patterns, merged
PRs, publications, verified credentials, systems built. The screening interface is a PDF. **The
evidence and the evaluation medium do not match**, so proxies (school names, buzzwords, polish)
substitute for substance.

### R3 — No structured prior
Hiring decisions are made against an unwritten cognitive checklist that varies by person, day, and
fatigue. No two candidates are compared the same way. The process cannot be inspected, learned from,
or defended.

### R4 — Channel fragmentation
Applications and conversations arrive through job portals, email, WhatsApp, LinkedIn, and physical
drops. There is no single pipeline, so candidates are forgotten, duplicated, or lost — and no one can
prove otherwise.

### R5 — Unaccountable decisions
Rejections leave no trace: no score, no reason, no signer, no appeal path. When process is invisible,
bias and error cannot be detected, let alone corrected. Historical screening data — the only record
that exists — encodes the very bias that audit studies measure.

### R6 — The automation trap
The obvious fix — "let AI screen for us" — has already failed once at scale: Amazon's ML recruiting
engine learned gender bias from ten years of résumés, penalized "women's" anything, downgraded
women's colleges, and also recommended unqualified candidates because the data itself was noise
(`dastin2018amazon`). Accelerating judgment that was never structured just scales the failure.

### R7 — Compliance debt
UU PDP No. 27/2022 creates duties (lawful basis, retention limits, data-subject rights, security)
that spreadsheet-and-WhatsApp recruitment cannot satisfy. GDPR Art. 22 and the EU AI Act's
classification of employment AI as high-risk (Annex III(4)(a); Art. 14) signal where regulation
everywhere is heading. Indonesian SMEs inherit these risks without any tooling to manage them.

---

## 4. Why existing tools don't solve it

| Existing solution | What it does | Why the problem persists |
|---|---|---|
| Job portals (Jobstreet, Glints, Kalibrr, Dealls) | Deliver candidate volume | More volume into the same bottleneck; screening not addressed |
| Traditional ATS (keyword filters) | Parses and filters CVs | Keyword matching *is* R2; no evidence evaluation, no explanation |
| HRIS platforms (Talenta, Gadjah, BambooHR) | Employee records, payroll workflows | Built for employees, not candidate evaluation; no technical depth |
| Spreadsheets | Free-form tracking | No structure, no audit, no automation, decays within weeks |
| Generic LLM chat (ChatGPT) | Draft text | No pipeline, no consistency, no audit, no HITL, no compliance; hallucination risk on consequential decisions |
| Enterprise AI screening | Automated ranking | Exactly the `dastin2018amazon` failure mode under outsourcing; unauditable; often illegal under GDPR Art. 22 |

**The gap:** an affordable, self-hostable, auditable system built for the **solo HR generalist**,
which evaluates *evidence* (not keywords), *explains every score*, and *reserves human judgment for
consequential decisions* — with Indonesian law and office reality (WhatsApp, Excel, Google) as
first-class citizens.

---

## 5. What "solved" looks like

Observable success criteria — each must be measurable in the system's own logs:

1. **Every candidate reaches a documented outcome.** No silent rejection; feedback within SLA.
2. **Every score is reproducible and inspectable.** Same inputs → same score; every score cites
   its evidence.
3. **No rejection above the merit floor without a named human.** Soft-rejection safeguard.
4. **Bias is measured, not assumed away.** Counterfactual name/attribute-swap audits pass at a
   defined rate; distributions are monitored.
5. **Time-to-first-response drops from never/days to < 24 hours** (automated, tracked).
6. **The HR person's screening time per role drops by an order of magnitude** while evaluation
   depth *increases* (deterministic scoring across full profiles).
7. **Compliance is operational, not aspirational.** Consent captured, retention enforced, data
   export/erasure supported, audit chain verifiable.
8. **It runs where the company needs it.** Self-hosted in their office or managed cloud — their
   data, their choice of model provider, including fully offline operation.

---

## 6. The design responses (traceability)

| Root cause | System response | Where |
|---|---|---|
| R1 attention physics | Agents read full artifacts; humans never scan 60 PDFs | ResumeDeconstructor, CodePortfolio |
| R2 encoding mismatch | Evaluation of artifacts: repos, AST metrics, publications, credentials | CodePortfolio tools |
| R3 no structured prior | Explicit job specification + deterministic tensor score S ∈ [0,1]^4 | Scorer, JobSpecification |
| R4 fragmentation | Unified ingestion + async candidate communication bridges | Ingestion API, ScreeningCoordinator |
| R5 unaccountability | Hash-chained audit log; score breakdowns; override records | AuditChain, policy engine |
| R6 automation trap | No outcome-trained models; LLMs extract, code decides, humans gate | Architecture-wide rule |
| R7 compliance debt | Consent records, retention fields, erasure workflows, HITL by design | Models, policy, Phase 8.9 |

---

## 7. Deliberate non-claims

- We do **not** claim to remove all bias. We claim to make decisions **inspectable and testable**,
  which is the precondition for reducing bias — and to structurally prevent the worst failure modes.
- We do **not** claim to replace the HR person. The system is built for them: it does reading,
  arithmetic, chasing, and drafting; they bring judgment, relationships, and accountability.
- We do **not** claim the desk-level observations above are statistically established for Indonesia;
  §2 is a design premise derived from documented global evidence plus regional practice, and
  validating it is an explicit Phase 10 goal.

---

## 8. Resolved questions

1. **Wedge:** screening volume is the product; candidate ghosting is the emotional hook.
   The wedge demo is "submit 50 CVs → ranked board with evidence breakdowns and a review queue."
2. **Market:** every company, not only large ones. The software is free and open source
   (Apache-2.0) so cost is never a barrier; the author offers paid freelance integration
   services for companies that want it running without the technical work.
3. **Money model:** freelance integration/setup/consulting. No SaaS billing, no paywalled
   features, no license gating. Managed hosting remains a deferrable option.
4. **The five-minute demo:** agreed — 50 CVs in, ranked board out, with evidence breakdowns and
   a human review queue. This is the "yes" moment in every sales conversation.
