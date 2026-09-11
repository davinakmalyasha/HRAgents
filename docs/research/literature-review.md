# Literature Review: Deterministic, Auditable Technical Recruitment

**Project:** HRAgents — Multi-Agent Candidate Evaluation Engine
**Document type:** Structured literature review supporting the technical paper and system design
**Research window:** Sources verified 2026-09-11
**Status:** Living document — expanded as the system evolves

---

## 0. Purpose and Method

### 0.1 Purpose

This review establishes the evidentiary foundation for a simple claim:

> Technical hiring in Indonesia (and globally) is bottlenecked not by a lack of candidates, but by
> screening processes that are **subjective, temporally constrained, structurally opaque, and legally
> unprepared**. Automation that merely accelerates those processes inherits their flaws. Automation
> that replaces *judgment* with *deterministic, auditable evaluation* — and reserves human judgment
> for decisions that materially affect people — can do better.

The review serves three purposes:

1. **Evidence for the paper's problem statement** — that legacy screening is measurably biased,
   time-constrained, and increasingly regulated.
2. **Design constraints for the system** — each finding below maps to a concrete architectural
   decision (see §7).
3. **Citation base** — a verified bibliography (`sources.bib`) so the paper makes no unsourced
   quantitative claims.

### 0.2 Method and inclusion criteria

Sources were retrieved and verified directly (not cited second-hand) on 2026-09-11. Verification
methods: direct retrieval of the published abstract/full text where accessible; archived captures
(Internet Archive Wayback Machine) where the publisher blocks automated access; official legal
databases for statutes; official statistics APIs for quantitative data.

Inclusion criteria:

- **Peer-reviewed or authoritative**: peer-reviewed journals (AER, PNAS), national/international
  statistics (World Bank Open Data, based on ILO modeled estimates), primary legal instruments
  (Regulation (EU) 2024/1689; GDPR; UU 27/2022), or reputable practitioner research (HBR; Ladders
  eye-tracking study).
- **Directly relevant** to one of: screening cognition, hiring discrimination, automation of hiring,
  AI regulation, or the Indonesian labor/legal context.
- **Verified**: every entry in §8 was accessible on the date shown. Contested or non-verifiable
  industry statistics (e.g., widely circulated but unsourced "75% of resumes are rejected by ATS"
  claims) were **excluded**.

### 0.3 Known limitations of this review

- Indonesian-language academic literature on algorithmic hiring is scarce; the Indonesian section
  relies on primary law and World Bank/ILO statistics rather than domestic hiring-funnel research,
  which does not appear to be publicly benchmarked. This is itself a finding (§5.3).
- Some sources are practitioner rather than peer-reviewed (Ladders, HBR). They are included for
  cognitive/operational claims, not for causal inference, and are labeled as such.
- The Amazon/Reuters case (§3.1) is investigative journalism, not a controlled study. It is treated
  as a documented industry case, and its internal details are attributed to named anonymous sources
  in the original reporting.

---

## 1. The Screening Bottleneck: Time-Bounded, Low-Fidelity Human Review

### 1.1 Evidence

**Ladders eye-tracking study (2012; updated 2018).** In an eye-tracking study of professional
recruiters reviewing résumés, Ladders found recruiters make an initial "fit / no fit" decision in
approximately **6 seconds** (2012) and updated the finding in 2018 to **7.4 seconds** using
eye-tracking data. The study also found that recruiters fixate on current title/company, then
previous position, then dates, then education — and that candidate photographs (common on online
profiles) actively delayed locating relevant skills and experience information.

- Source: Ladders Eye-Tracking Study; Ladders article, archived captures 2019-01-02 and
  2020-12-30 (`sources.bib`: `ladders2018eyetracking`).
- Interpretation: the "7.4 seconds" figure is a *median initial scan*, not total evaluation time.
  It does not mean hiring decisions take 7.4 seconds — but it does mean that **whatever a résumé
  fails to communicate in its first few visual seconds is at severe risk of never being considered**.
  Keyword-shaped résumés win; substance-dense résumés that require reading lose.

**HBR — Cappelli (2019), "Your Approach to Hiring Is All Wrong."** Cappelli's central argument:
"Businesses have never done as much hiring as they do today. They've never spent as much money
doing it. And they've never done a worse job of it." He attributes the failure to outsourced
sourcing, broken algorithms, and the absence of structured evaluation, and notes that the
companion piece's title — "Data Science Can't Fix Hiring (Yet)" — reflects the immaturity of
data-driven hiring rather than its impossibility.

- Source: Harvard Business Review, May–June 2019 issue (`sources.bib`: `cappelli2019hiring`).

### 1.2 Synthesis

Human screening at scale is **structurally lossy**:

| Property | Human screening reality | Consequence |
|---|---|---|
| Attention budget | ~7 seconds per résumé, initial pass | Dense technical evidence is skipped |
| Consistency | Varies by mood, time of day, workload, fatigue | Non-reproducible decisions |
| Evidence depth | Keyword matching, visual salience | Portfolio/metadata ignored |
| Record | Usually none | Decisions cannot be audited or challenged |
| Feedback | Usually none | Candidates cannot learn or contest |

This is not recruiter incompetence; it is an impossible workload. A human cannot perform deep
technical evaluation thousands of times per week, and should not be asked to.

---

## 2. Subjectivity and Discrimination: The Empirical Record

### 2.1 Bertrand & Mullainathan (2004) — résumé audit

The canonical field experiment in hiring discrimination: fictitious résumés with randomly assigned
White- or African-American-sounding names were sent to job ads in Boston and Chicago. **White names
received 50 percent more callbacks for interviews.** Callback rates were more responsive to résumé
quality for White names than for Black names, and the racial gap was **uniform across occupation,
industry, and employer size**.

- Source: *American Economic Review* 94(4), September 2004, pp. 991–1013.
  DOI: [10.1257/0002828042002561](https://doi.org/10.1257/0002828042002561). Abstract verified
  directly (`sources.bib`: `bertrand2004emily`).

### 2.2 Quillian, Pager, Hexel & Midtbøen (2017) — meta-analysis

A meta-analysis of field experiments (audit studies) across multiple countries and decades. Title
finding, verified via the published record: **no change in racial discrimination in hiring over
time** — callback gaps between majority and minority applicants remained essentially stable.

- Source: *PNAS* 114(41), October 2017, pp. 10870–10875.
  DOI: [10.1073/pnas.1706255114](https://doi.org/10.1073/pnas.1706255114)
  (`sources.bib`: `quillian2017meta`).

### 2.3 Synthesis

Two independent, methodologically strong lines of evidence establish that:

1. Discrimination in initial screening is **large, persistent, and not self-correcting** — it did
   not diminish over the decades studied.
2. It operates at the **earliest, lowest-information stage** (the callback decision), exactly where
   current ATS pipelines concentrate automation.
3. Any system trained to imitate historical screening decisions inherits this signal. This is the
   direct cause of the failure described in §3.

**Design implication (carried into §7):** names, gender, photos, nationality, religion, and other
protected attributes must be excluded from scoring by construction — and this must be *tested*,
not merely asserted. The audit-study methodology in §2.1 can be adapted as an internal fairness
protocol: periodically inject counterfactual variants of the same candidate profile (names swapped,
demographic markers removed) and verify score invariance.

---

## 3. Automation Failures: Why "AI Screening" Has Failed Once Already

### 3.1 Amazon's machine-learning recruiting engine (Reuters, 2018)

Reuters documented Amazon's internal ML recruiting effort in detail:

- Starting in 2014, a team in Edinburgh built **500 computer models** for specific job functions and
  locations, trained on candidate résumés submitted over a **10-year period** and roughly **50,000
  terms**.
- By 2015, Amazon discovered the system was **not gender-neutral**: because historical résumés came
  overwhelmingly from men, the models "taught itself that male candidates were preferable."
  It **penalized résumés containing the word "women's"** (e.g., "women's chess club captain") and
  **downgraded graduates of two all-women's colleges**.
- Bias was not the only failure: "Problems with the data that underpinned the models' judgments
  meant that unqualified candidates were often recommended for all manner of jobs." The tool
  returned results "almost at random."
- Amazon reportedly edited the models to neutralize specific terms, concluded the systemic issue
  could not be guaranteed fixed, and **disbanded the team**; a "much-watered down version" was
  later retained for chores such as de-duplicating candidate profiles.
- The stated industry ambition at the time: "They literally wanted it to be an engine where I'm
  going to give you 100 resumes, it will spit out the top five, and we'll hire those."
- LinkedIn's John Jersin, in the same article: **"I certainly would not trust any AI system today
  to make a hiring decision on its own. The technology is just not ready yet."**
- Context statistic cited in the article: a 2017 CareerBuilder survey found **55% of U.S. HR
  managers expected AI to be a regular part of their work within five years**.

- Source: Dastin, J. (2018-10-10), Reuters, "Amazon scraps secret AI recruiting tool that showed
  bias against women" (`sources.bib`: `dastin2018amazon`). Full text verified 2026-09-11.

### 3.2 Synthesis — the core lesson

The Amazon case is not an argument against automation. It is an argument against **learning
preferences from historical human decisions**, and against **opaque models making consequential
judgments**. The historical data encoded human bias and noise at the same time — the model learned
both, and could not distinguish them.

Three failure modes to engineer against (all appear simultaneously in §3.1):

1. **Proxy learning** — the model used correlated features (words, institution names, writing style)
   as stand-ins for merit.
2. **Opaqueness** — executives could not determine whether the bias was removed because the model's
   reasoning was not inspectable.
3. **Decision authority** — the system was positioned to *rank and eliminate* people, the highest-
   stakes use, before it was demonstrably fit for the lowest-stakes use.

**Design implication (carried into §7):** no training on historical hiring outcomes; LLMs used for
*extraction* (résumé → structured facts with provenance) rather than *judgment*; scoring expressed
as a transparent, inspectable function with explicit factors; human sign-off required for
consequential negative actions.

---

## 4. Regulatory Landscape: High-Risk Classification Is Now Explicit

### 4.1 EU AI Act — Regulation (EU) 2024/1689

The EU AI Act explicitly classifies employment-related AI as **high-risk**. Annex III, point 4
("Employment, workers' management and access to self-employment"), sub-point (a), covers:

> "AI systems intended to be used for the recruitment or selection of natural persons, in particular
> to place targeted job advertisements, to analyse and filter job applications, and to evaluate
> candidates."

High-risk systems trigger obligations relevant to this project, including (titles verified in the
Act's structure): risk management (Art. 9), data governance (Art. 10), technical documentation
(Art. 11), **record-keeping (Art. 12)**, transparency (Art. 13), **human oversight (Art. 14)**,
accuracy/robustness/cybersecurity (Art. 15), and **automatically generated logs (Art. 19)**.

**Article 14 (Human Oversight)** — key provisions verified:

- Oversight must be *effective*, including human-machine interface tools (14(1)).
- Oversight aims to prevent or minimise risks to fundamental rights, including **non-discrimination**
  (14(2)).
- Oversight measures must let the human: understand the system's capacities and limits and **detect
  anomalies, dysfunctions and unexpected performance** (14(4)(a)); remain aware of **automation
  bias** (14(4)(b)); correctly interpret output (14(4)(c)); **disregard, override or reverse**
  output (14(4)(d)); and **interrupt** the system (14(4)(e)).

**Article 86** grants a right to explanation of individual decision-making for affected persons
(title verified; detailed conditions in the Act).

- Sources: EUR-Lex ELI `reg/2024/1689/oj`; verified text mirror at
  `artificialintelligenceact.eu/annex/3/` and `/article/14/` (`sources.bib`: `eu2024aiact`).
- Note on timing: the Act enters into application in staged phases. The explorer states that
  Annex III high-risk obligations apply from **2 December 2027**. The *design* implications are
  relevant regardless, and the Act is a global reference standard.

### 4.2 GDPR — Regulation (EU) 2016/679, Article 22

Even where a jurisdiction lacks an AI-specific statute, data-protection law often governs automated
hiring. GDPR Article 22 (verified full text):

- 22(1): data subjects have the right not to be subject to a decision **based solely on automated
  processing** that produces legal effects or similarly significantly affects them.
- 22(3): where such decisions are permitted, the controller must implement safeguards including
  **the right to obtain human intervention, to express their point of view, and to contest the
  decision**.

- Source: `gdpr-info.eu/art-22-gdpr/` (`sources.bib`: `gdpr2016art22`).

### 4.3 Indonesia — UU No. 27 Tahun 2022 (Pelindungan Data Pribadi)

Indonesia's Personal Data Protection Law, enacted and effective **17 October 2022**
(LN.2022/No.196; TLN No.6820), establishes the national framework for processing personal data.
Verified from the official JDIH/BPK database:

- Personal data is split into **specific** categories (health data; biometric data; genetic data;
  criminal records; data concerning children; personal financial data; and/or data otherwise
  designated) and **general** categories (full name; sex; nationality; religion; marital status;
  and/or combinations used to identify a person).
- The law regulates: principles; types of personal data; **data-subject rights**; processing;
  **controller and processor obligations**; transfers; administrative sanctions; the supervisory
  institution; international cooperation; dispute resolution; prohibited uses; and **criminal
  provisions**.
- Purpose anchors include protection of the right to personal self-protection under the 1945
  Constitution.

- Source: peraturan.bpk.go.id, *UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi*
  (`sources.bib`: `indonesia2022pdp`).

**Hiring-specific reading:** candidate CVs, phone numbers, email addresses, photos, birth dates,
salary history, and assessment outputs are personal data. A recruitment platform is a **data
controller/processor** under UU PDP. Consent, purpose limitation, retention limits (no indefinite
"talent pools"), data-subject access/correction/erasure rights, and security obligations apply.
Automated evaluation additionally produces new personal data (scores, flags) that inherit those
obligations.

### 4.4 Standards references

- **NIST AI Risk Management Framework (AI RMF 1.0)**, NIST AI 100-1 (January 2023) — voluntary
  framework structured around Govern, Map, Measure, Manage; widely used as the operational baseline
  for AI risk programs (`sources.bib`: `nist2023airmf`).
- **ISO/IEC 42001:2023** — AI management systems standard, used for organizational governance of
  AI (`sources.bib`: `iso42001`).

### 4.5 Synthesis

The regulatory direction is unambiguous: **automated employment screening is now explicitly
governed, and human oversight is a legal requirement, not a feature choice.** A system designed to
*auto-reject* candidates without human involvement sits close to the statutory line in multiple
jurisdictions (GDPR Art. 22; EU AI Act human-oversight duties; UU PDP's lawful-processing and
rights regime). A system that auto-*schedules* (reversible, positive, low-harm) while requiring a
human for rejections (consequential, negative, hard to reverse) is aligned with every framework
reviewed here.

---

## 5. The Indonesian Context

### 5.1 Macro labor statistics (verified)

World Bank Open Data, based on ILO modeled estimates, accessed 2026-09-11 (dataset last updated
2026-07-13) (`sources.bib`: `worldbank2026indonesia`):

| Indicator | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|
| Unemployment, total (% of labor force) `SL.UEM.TOTL.ZS` | 4.255 | 3.827 | 3.462 | 3.308 | 3.301 |
| Unemployment, youth 15–24 (% of labor force 15–24) `SL.UEM.1524.ZS` | 14.773 | 13.800 | 14.054 | 13.015 | 13.075 |

Interpretation:

- Headline unemployment is comparatively low (~3.3%), but **youth unemployment is ~4x higher
  (~13%)** — with roughly one in eight young labor-force participants unemployed (modeled estimate).
- The youth cohort is exactly the population applying for entry-level technical roles through
  high-volume funnels. Screening failure at scale hits them hardest.
- Caveat: modeled ILO estimates differ from national BPS survey figures; they are used here for
  comparability, with the source and method disclosed.

### 5.2 Hiring-practice observations (qualitative; no verified domestic dataset exists)

Based only on common, documented regional practice and the absence of countervailing evidence —
labeled as qualitative, not statistical:

- Applications arrive through mixed channels: job portals, email, LinkedIn, and in many companies
  **WhatsApp** — creating fragmented records with no single source of truth.
- Recruiters frequently operate without structured role specifications; screening heuristics are
  personal rather than documented.
- Feedback to rejected candidates is rare or boilerplate; response latency is often indefinite.
- "Overqualified" and "underqualified" are used as rejection categories without operational
  definitions.

These observations are included because they motivate product requirements (multi-channel
ingestion, explicit role specification scoring, guaranteed response SLAs, defined factor scoring)
— but they are *not* cited as measured facts, and the paper must present them as design premises
requiring validation.

### 5.3 Research gap

No public, methodologically transparent benchmark of Indonesian technical hiring funnels was located
during this review. The paper should therefore:

1. Use the global evidence (§1–§3) as the problem statement.
2. Treat Indonesian specifics as **premises and constraints** (law, channels, WhatsApp prevalence),
   not quantified facts.
3. Position the system's own logs as a future contribution: an auditable dataset of *how* screening
   decisions are actually made — which the current ecosystem does not produce.

---

## 6. Skills-Based Hiring and Global Demand Signals

The World Economic Forum's **Future of Jobs Report 2025** (published 7 January 2025) aggregates the
views of over 1,000 employers representing 14+ million workers across 22 industry clusters and 55
economies, covering 2025–2030. It documents technological change, economic uncertainty, demographic
shifts and the green transition as labor-market drivers, and reports that **skills gaps are among
the principal barriers to business transformation**, with reskilling/upskilling central to employer
strategies.

- Source: WEF, *Future of Jobs Report 2025* (`sources.bib`: `wef2025futureofjobs`).

Relevance:

- The report's employer-level perspective confirms demand-side pressure toward **skills-based
  evaluation** rather than credential-based screening.
- A system that evaluates *demonstrated capability* (code, complexity metrics, verified artifacts,
  publication records) directly operationalizes the skills-based direction — while a 7.4-second
  human scan (see §1) cannot.
- Caveat: the report is employer-survey-based (self-reported), so it evidences *intent and
  perception*, not measured hiring outcomes.

---

## 7. Synthesis: Evidence → Design Principles

Every architectural commitment in HRAgents traces to a finding above. This mapping is normative:
it defines what the system must do to honestly claim it addresses the evidence.

| # | Finding (source) | Design principle (system response) |
|---|---|---|
| P1 | Screens operate in seconds; dense evidence is skipped (§1.1) | **Extraction before judgment.** Agents read and structure the full profile, not a 7-second glance. |
| P2 | Human screening is inconsistent and unauditable (§1.2) | **Deterministic scoring.** The same inputs must produce the same score, with the formula and every input exposed. |
| P3 | Discrimination is large, persistent, and enters at callback/screening (§2) | **Constructive blindness + fairness testing.** Protected attributes are excluded from scoring; counterfactual name/attribute-swap audits run continuously. |
| P4 | Learning from historical hiring decisions reproduces bias and noise (§3.1) | **No outcome-trained ranking models.** Scoring is a hand-specified, inspectable function; LLMs never rank by "fit". |
| P5 | Opaque models cannot be audited (§3.2) | **Provenance + hash-chained audit log.** Every score cites its evidence; every decision is reconstructible. |
| P6 | AI hiring evaluations are explicitly high-risk; human oversight is a legal duty (§4) | **HITL gates.** Auto-schedule only for high-confidence, positive actions; every rejection above a technical-merit floor requires named human sign-off. |
| P7 | Solely automated consequential decisions are restricted; contestants have rights (§4.2–4.3) | **Contestable outcomes.** Feedback reports, explanation endpoints, and override/appeal paths. |
| P8 | Candidate data is protected personal data; retention and consent are obligations (§4.3) | **Compliance as architecture.** Consent capture, data minimization, retention policies, erasure workflows, RBAC, PII redaction before model calls. |
| P9 | Employers want skills evidence, not credentials (§6) | **Artifact-based evaluation.** Repositories, AST complexity, publications, verified certifications are first-class signals. |
| P10 | Indonesian funnels are fragmented across channels (§5.2) | **Unified async ingestion + candidate communication.** WhatsApp/Telegram/email bridges, one candidate record, guaranteed response SLA. |

### 7.1 The resulting thesis statement

> Replace subjective screening with **deterministic technical evaluation**:
> LLM agents *extract* verifiable evidence into structured JSON; a hand-specified, inspectable
> **tensor score** evaluates that evidence; **humans own every consequential negative decision**;
> and every step is recorded in a tamper-evident audit trail. Automation does the reading,
> arithmetic, and logistics. People do the judging — with better evidence and less bias, not less
> accountability.

### 7.2 What this review does *not* claim

- It does not claim LLMs are unbiased. It claims their *role* can be constrained to extraction,
  where bias affects fidelity (testable) rather than opportunity (consequential).
- It does not claim deterministic scoring is fair by itself. It claims it is **inspectable**,
  which is the precondition for auditing fairness. Fairness must be measured, per §2.1's
  methodology, not assumed.
- It does not claim the Indonesian observations in §5.2 are statistically established. They are
  premises the system is built to test and record.

---

## 8. Source Verification Table

All sources accessed 2026-09-11 unless noted. "Verified via" states exactly what was retrieved.

| Key | Source | Type | Verified via | Supports |
|---|---|---|---|---|
| `bertrand2004emily` | Bertrand & Mullainathan (2004), AER 94(4):991–1013 | Peer-reviewed | AEA abstract page, full abstract | §2.1 discrimination magnitude |
| `quillian2017meta` | Quillian et al. (2017), PNAS 114(41):10870–10875 | Peer-reviewed meta-analysis | DOI resolution + publication record | §2.2 persistence of discrimination |
| `dastin2018amazon` | Reuters (2018), Amazon AI recruiting tool | Investigative journalism | Full text retrieved | §3.1 automation failure case |
| `ladders2018eyetracking` | Ladders eye-tracking study (2012; updated 2018) | Practitioner study | Two Wayback captures (2019, 2020) incl. article text and study PDF link | §1.1 6 s / 7.4 s scan time |
| `cappelli2019hiring` | Cappelli (2019), HBR May–Jun 2019 | Practitioner article | Article page + summary block | §1.1 hiring process critique |
| `eu2024aiact` | Regulation (EU) 2024/1689 (AI Act) | Primary law | Annex III + Art. 14 full text mirrors; EUR-Lex ELI | §4.1 high-risk + oversight duties |
| `gdpr2016art22` | Regulation (EU) 2016/679, Art. 22 | Primary law | Full article text | §4.2 automated decision rights |
| `indonesia2022pdp` | UU No. 27/2022 (Pelindungan Data Pribadi) | Primary law | Official BPK/JDIH record + abstract | §4.3 Indonesian data law |
| `worldbank2026indonesia` | World Bank Open Data (ILO modeled estimates) | Official statistics | Live API query, JSON values above | §5.1 labor statistics |
| `wef2025futureofjobs` | WEF Future of Jobs Report 2025 | Employer survey report | Official publication page | §6 skills-based demand |
| `nist2023airmf` | NIST AI RMF 1.0 / NIST AI 100-1 (2023) | Standards framework | Standard reference (not fetched) | §4.4 risk governance |
| `iso42001` | ISO/IEC 42001:2023 | Standards framework | Standard reference (not fetched) | §4.4 AI management systems |
| `pydanticai` | PydanticAI documentation | Software documentation | Project documentation site | Implementation basis (Ch. systems) |

---

## 9. References

1. Bertrand, M., & Mullainathan, S. (2004). Are Emily and Greg More Employable Than Lakisha and Jamal? A Field Experiment on Labor Market Discrimination. *American Economic Review*, 94(4), 991–1013. https://doi.org/10.1257/0002828042002561
2. Quillian, L., Pager, D., Hexel, O., & Midtbøen, A. H. (2017). Meta-analysis of field experiments shows no change in racial discrimination in hiring over time. *Proceedings of the National Academy of Sciences*, 114(41), 10870–10875. https://doi.org/10.1073/pnas.1706255114
3. Dastin, J. (2018, October 10). Insight: Amazon scraps secret AI recruiting tool that showed bias against women. Reuters. https://www.reuters.com/article/us-amazon-com-jobs-automation-insight-idUSKCN1MK08G
4. Ladders. (2018). *Eye-Tracking Study* (TheLadders-EyeTracking-StudyC2.pdf); article: "You have 7.4 seconds to make an impression: How recruiters see your resume." Archived: https://web.archive.org/web/20201230113653/https://www.theladders.com/career-advice/you-only-get-6-seconds-of-fame-make-it-count
5. Cappelli, P. (2019, May–June). Your Approach to Hiring Is All Wrong. *Harvard Business Review*. https://hbr.org/2019/05/your-approach-to-hiring-is-all-wrong
6. European Union. (2024). Regulation (EU) 2024/1689 of the European Parliament and of the Council laying down harmonised rules on artificial intelligence (AI Act). https://eur-lex.europa.eu/eli/reg/2024/1689/oj
7. European Union. (2016). Regulation (EU) 2016/679 (General Data Protection Regulation), Article 22. https://gdpr-info.eu/art-22-gdpr/
8. Republic of Indonesia. (2022). Undang-Undang Nomor 27 Tahun 2022 tentang Pelindungan Data Pribadi (LN.2022/No.196, TLN No.6820). https://peraturan.bpk.go.id/Details/229798/uu-no-27-tahun-2022
9. World Bank. (2026). Unemployment, total and youth (ILO modeled estimates) — Indonesia [Data set]. World Bank Open Data. https://api.worldbank.org/v2/country/IDN/indicator/SL.UEM.1524.ZS
10. World Economic Forum. (2025). *The Future of Jobs Report 2025*. https://www.weforum.org/publications/the-future-of-jobs-report-2025/
11. National Institute of Standards and Technology. (2023). *Artificial Intelligence Risk Management Framework (AI RMF 1.0)* (NIST AI 100-1). https://doi.org/10.6028/NIST.AI.100-1
12. ISO/IEC. (2023). *ISO/IEC 42001:2023 — Information technology — Artificial intelligence — Management system*.
13. Pydantic. (2026). PydanticAI documentation. https://ai.pydantic.dev/
