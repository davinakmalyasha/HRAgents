# System Architecture

**Version:** 0.1.0 · **Status:** contracts frozen, implementation in progress

## 1. Overview

HRAgents is a four-stage pipeline with one rule: **agents extract, code decides, humans gate.**

```
Extract (LLM, nondeterministic)  →  Score (pure Python, deterministic)  →  Gate (policy + HITL)  →  Communicate (bridges + feedback)
```

The system is designed against the evidence base in `docs/research/literature-review.md`:
screening decisions must be fast, consistent, inspectable, non-discriminatory, and contestable.

## 2. End-to-end flow

```mermaid
flowchart LR
    subgraph Clients
        ATS["ATS / Portal"]
        EMAIL["Email inbox"]
        WA["WhatsApp / Telegram"]
        API["Direct API clients"]
    end

    subgraph Edge["Edge & Ingestion"]
        LB["Load balancer"]
        APIAPP["FastAPI ingestion API<br/>(async, 10k req/min target)"]
        IDEM["Idempotency store<br/>(Postgres)"]
    end

    subgraph Storage["Object & Document"]
        S3["MinIO / S3<br/>raw documents (encrypted)"]
        PARSE["Document parser<br/>PDF/DOCX → text<br/>(PII redaction)"]
    end

    subgraph Queue["Work orchestration"]
        STREAM["Redis Streams<br/>consumer groups"]
        SORTED["Redis sorted set<br/>priority index"]
        WORKERS["Worker pool<br/>(asyncio)"]
    end

    subgraph Agents["Agent layer (PydanticAI)"]
        RESUME["ResumeDeconstructor<br/>→ CandidateProfile"]
        CODE["CodePortfolio<br/>GitHub + AST analysis"]
        SCREEN["AsyncScreening<br/>availability + clarifications"]
        FB["FeedbackWriter"]
        GUARD["InjectionGuard<br/>(sanitize untrusted input)"]
    end

    subgraph Deterministic["Deterministic layer (no LLM)"]
        SCORER["Vector Scorer<br/>S ∈ [0,1]^4, k=3 runs"]
        PRIORITY["Priority ranker<br/>P = α·S̄ + β·e^(−λΔt) + γ·A − δ·R"]
        POLICY["Policy engine<br/>auto-schedule vs HITL gates"]
    end

    subgraph Data["Persistence"]
        PG[("PostgreSQL 16<br/>profiles, evals, jobs")]
        AUDIT[("Hash-chained<br/>audit log")]
    end

    subgraph Human["Human-in-the-loop"]
        CONSOLE["Reviewer console<br/>queues, score breakdowns"]
        OVERRIDE["Override API<br/>(named sign-off)"]
    end

    subgraph Outbound["Communication"]
        MSG["Messaging bridges"]
        CAL["Calendar adapters"]
    end

    ATS --> LB
    EMAIL --> LB
    WA --> LB
    API --> LB
    LB --> APIAPP
    APIAPP --> IDEM
    APIAPP --> S3
    APIAPP --> STREAM
    S3 --> PARSE
    PARSE --> STREAM
    STREAM --> WORKERS
    WORKERS --> GUARD
    GUARD --> RESUME
    GUARD --> CODE
    GUARD --> SCREEN
    RESUME --> SCORER
    CODE --> SCORER
    SCORER --> PRIORITY
    SCORER --> POLICY
    PRIORITY --> SORTED
    POLICY -->|auto_schedule| CAL
    POLICY -->|gate| CONSOLE
    CONSOLE --> OVERRIDE
    OVERRIDE --> AUDIT
    POLICY --> AUDIT
    SCORER --> PG
    RESUME --> PG
    CODE --> PG
    FB --> MSG
    SCREEN --> MSG
    CAL --> MSG
```

## 3. HITL soft-rejection flow

The most consequential path in the system: a candidate scores above the technical-merit floor
but below the advance bar. No rejection may be sent without a named human sign-off.

```mermaid
sequenceDiagram
    autonumber
    participant W as Worker
    participant S as Deterministic Scorer
    participant P as Policy Engine
    participant Q as Reviewer Queue
    participant L as Engineering Lead
    participant A as Audit Log
    participant M as Messaging Bridge

    W->>S: CandidateProfile + JobSpecification
    S->>S: k=3 independent extraction+score runs
    S->>P: mean_vector, s_tech, sigma, flags
    P->>P: apply thresholds (0.70 <= s_tech < 0.85)
    P->>Q: enqueue HITL_SOFT_REJECTION (breakdown attached)
    P->>A: append policy decision (hash-chained)
    Q->>L: reviewer opens full score breakdown
    alt Lead concurs with rejection
        L->>Q: override_decision = reject_requires_signoff + reason_code
        Q->>A: append named sign-off (actor = human)
        Q->>M: send rejection + feedback report
    else Lead overturns
        L->>Q: override_decision = human_review (advance)
        Q->>A: append overturn (actor = human)
        Q->>M: invite to next stage
    else No decision within 72h
        Q->>A: append escalation (SLA breach)
        Q->>Q: escalate to HITL_MANUAL — candidate is never silently rejected
    end
```

## 4. Application lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued: ingestion accepted (202)
    queued --> processing: worker leases job
    processing --> extraction_failed: parse/agent failure (retry ≤ 3)
    extraction_failed --> processing: retry
    extraction_failed --> needs_manual_triage: retries exhausted
    processing --> evaluated: deterministic score computed
    evaluated --> auto_schedule: S_tech ≥ 0.85 ∧ σ ≤ 0.05 ∧ no flags ∧ slots ≥ 2
    evaluated --> gated: flags ∨ 0.70 ≤ S_tech < 0.85 ∨ slots < 2
    gated --> scheduled: human approves advance
    gated --> rejected: human signs off rejection
    evaluated --> rejected: S_tech < 0.70 ∧ no flags
    auto_schedule --> scheduled: candidate confirms slot
    scheduled --> [*]
    rejected --> [*]
    needs_manual_triage --> gated
```

## 5. Components

| Component | Responsibility | Deterministic? | Notes |
|---|---|---|---|
| Ingestion API | Accept applications, validate, persist, enqueue | Yes | Returns `202`; idempotency-keyed |
| Document parser | PDF/DOCX → text; hash; PII redaction | Yes | Redaction precedes any LLM call |
| InjectionGuard | Neutralize prompt injection in untrusted text | Yes (rules) | LLM-visible content is sanitized |
| ResumeDeconstructor | Résumé text → `CandidateProfile` | No (LLM) | Output validated by Pydantic v2; every field carries provenance |
| CodePortfolioAgent | GitHub + AST metrics (complexity, tests, deps) | Mixed | Numeric metrics deterministic; summaries LLM-assisted |
| Deterministic Scorer | Evidence → `ScoreVector`, k=3, aggregation | **Yes** | Pure Python; no model calls |
| Priority ranker | `P = α·S̄ + β·e^(−λ·Δt) + γ·A − δ·R` | **Yes** | Redis sorted set; p99 < 50 ms |
| Policy engine | Automation gates per §7 | **Yes** | Thresholds snapshotted into every decision |
| AsyncScreeningAgent | Availability, clarifications, consent | No (LLM) | Sandbox mode by default; human handoff available |
| FeedbackWriter | Candidate-facing report | No (LLM) | Constrained to deterministic breakdown; no internal notes |
| Audit writer | Append-only hash chain | **Yes** | `entry_hash` covers payload + `prev_hash` |
| Reviewer console | Queues, breakdowns, override actions | N/A | Human interface; RBAC-enforced |

## 6. Data model (core entities)

```mermaid
erDiagram
    CANDIDATES ||--o{ APPLICATIONS : submits
    JOBS ||--o{ APPLICATIONS : receives
    CANDIDATES ||--o{ EVALUATIONS : evaluated_by
    JOBS ||--o{ EVALUATIONS : scopes
    CANDIDATES ||--o{ SCHEDULE_PROPOSALS : scheduled_via
    CANDIDATES ||--o{ CONVERSATIONS : converses
    CONVERSATIONS ||--o{ MESSAGES : contains

    CANDIDATES {
        uuid id PK
        text full_name
        jsonb profile
        jsonb consent
        timestamptz retention_expires_at
    }
    APPLICATIONS {
        uuid id PK
        uuid candidate_id FK
        uuid job_id FK
        text status
        text idempotency_key UK
        float priority_score
    }
    EVALUATIONS {
        uuid id PK
        uuid candidate_id FK
        float s_tech
        float sigma
        text recommendation
        jsonb document
    }
    AUDIT_LOG {
        int seq PK
        uuid entry_id UK
        text entry_hash UK
        text prev_hash
        jsonb payload
    }
```

## 7. Latency and throughput budget

| Path | Target | Mechanism |
|---|---|---|
| Ingestion accept (`POST /v1/applications`) | p99 < 150 ms | Async write + enqueue only; no synchronous processing |
| Sustained ingestion | 10,000 req/min | Horizontal API replicas; Redis Streams backpressure |
| Priority queue read (`GET /v1/queue`) | p99 < 50 ms | Precomputed sorted set; cursor pagination |
| Deterministic scoring | < 100 ms per candidate | Pure Python over JSON; k=3 runs |
| Full extraction pipeline | < 10 min p95 | Async workers; bounded retries with dead-letter |
| First candidate-facing response | < 24 h | SLA timer per conversation |

## 8. Failure modes and mitigations

| Failure | Mitigation |
|---|---|
| LLM output invalid/malformed | Pydantic v2 validation + bounded retries; profile marked `low_confidence_extraction` |
| LLM unavailable | Degraded mode: deterministic scoring over parsed structured fields; queue holds work |
| Extraction variance too high (σ > 0.05) | Auto-scheduling blocked; routed to human review |
| Prompt injection in résumé | InjectionGuard + output validation; injection flags force HITL |
| Duplicate submissions | Idempotency keys; document hashing; profile de-duplication |
| Calendar starvation (< 2 slots) | HITL_CALENDAR routing; candidate communication continues |
| Audit tampering | Hash chain verification job; any mismatch raises a blocking incident |
| Consent revoked mid-pipeline | `has_active_consent` checkpoint; processing halts; retention job purges per policy |

## 9. Security and compliance touchpoints

- **PII redaction before model calls** — names, photos, addresses, birth dates, and protected
  attributes never reach scoring, and are minimized in model prompts.
- **No protected attributes in scoring** — enforced by schema (scoring consumes only the four
  job-relevant dimensions) and verified by the fairness harness (counterfactual name-swap audits).
- **RBAC** — override endpoints restricted to `engineering_lead`, `recruiter_lead`, `hr_partner`.
- **Audit chain** — every policy decision, score, override, and outbound notification is appended
  with `prev_hash`/`entry_hash`.
- **Retention** — per-entity operator policies (months + delete/anonymize) over the retention ledger;
  scheduled purge skips legal holds and reports uncovered entities. No statutory window is hardcoded.
- **Data-subject rights** — consent registry, retention scan/purge, erasure workflow (human identity
  verification → Data Protection approval → separate human execution), and explanation via feedback
  reports map to UU PDP obligations. Implementation: `hr_agents.services.compliance`.

## 10. Cross-references

- Automation boundaries and thresholds: `docs/architecture/hitl-bounds.md`
- Evidence and design rationale: `docs/research/literature-review.md`
- API contract: `docs/api/openapi.yaml`
