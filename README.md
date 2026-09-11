# HRAgents — A Virtual HR Team for the HR Department of One

> One HR generalist, ten jobs, no time. HRAgents gives them a team: agents that read,
> chase, calculate, and draft — while humans keep every decision that matters.

**Free and open source (Apache-2.0).** Self-host it, inspect it, modify it. The author
offers paid integration services for companies that want it running without the
technical work — see [Work with the author](#work-with-the-author).

**Status:** active development. Platform core, agents, recruitment API surface, and all
Wave-1 department engines are operational (731 tests, 92% coverage); the dashboard, MCP
layer, and public release are next. No public release yet — see the
[remaining work plan](docs/plan/remaining-work.md).

---

## Why this exists

Indonesian SMEs run hiring and HR on one overloaded person, WhatsApp, and spreadsheets.
The failure is structural, and it is documented:

- **Measured**: recruiters make initial résumé fit decisions in ~7.4 seconds (Ladders
  eye-tracking study), and hiring discrimination has remained essentially unchanged for
  decades (Quillian et al., PNAS 2017; Bertrand & Mullainathan, AER 2004).
- **Documented**: Amazon's ML recruiting engine learned gender bias from 10 years of
  résumés and was disbanded (Reuters, 2018). Accelerating bad judgment scales the failure.
- **Regulated**: recruiting AI is classified high-risk (EU AI Act, Annex III(4)(a));
  solely automated consequential decisions are restricted (GDPR Art. 22); candidate and
  employee data are protected personal data in Indonesia (UU PDP No. 27/2022).

The fix is not "let AI decide." The fix is **agents extract evidence, deterministic code
scores it, and humans gate every consequential decision** — with a tamper-evident record
of everything.

## What it does

> **Extract → Score → Gate → Communicate**

1. **Extract** — LLM agents (PydanticAI) turn résumés, repositories, and documents into
   structured, provenance-tagged JSON. The LLM never judges a person; it structures facts.
2. **Score** — a hand-specified, deterministic function computes the tensor score
   `S ∈ [0,1]^4`: technical depth, stack alignment, systems literacy, verifiable
   certifications. Same input, same score, every time — fully inspectable.
3. **Gate** — auto-scheduling only for high-confidence positive outcomes
   (`S_tech ≥ 0.85`, `σ ≤ 0.05`). Every rejection above the merit floor needs a named
   human signature. Anomalies always route to humans.
4. **Communicate** — async candidate screening (WhatsApp / Telegram / email) collects
   availability and missing information, with response SLAs so no candidate is ghosted.

Every step lands on a hash-chained audit log. Every score cites its evidence.

### Core formulas (locked)

**Queue priority** — merit balanced against waiting time and risk:

```
P(c) = α·S̄(c) + β·e^(−λ·Δt) + γ·A(c) − δ·R(c)
```

`S̄` weighted score mean · `Δt` hours since submission · `A` availability completeness ·
`R` risk flags. Defaults: `α=0.55, β=0.25, γ=0.10, δ=0.10, λ=0.05/h`; ties broken by
earliest submission.

**Automation gates** — auto-schedule iff `S_tech ≥ 0.85 ∧ σ ≤ 0.05`; mandatory human
review for `S_tech ≥ 0.70` rejections.

## The plan: one HR person, eight workspaces

| Workspace | Wave | Agents do | Humans gate |
|---|---|---|---|
| **Hiring** | 1 (building) | Extract, score, coordinate, draft | Every rejection, every offer |
| **Ask HR** (front door) | 1 | Intent routing, cited policy Q&A | Anything consequential |
| **Onboarding** | 1–2 | Checklists, document chasing | Contracts, signatures |
| **People** | 2 | Records, expiry alerts, retention | Corrections, sensitive fields |
| **Leave** | 2 | Balance math, policy Q&A, routing | Every approval |
| **Payroll** | 3 | Assemble, calculate, flag, export | **Everything — no payment is ever executed** |
| **Growth** | 3 | Reminders, collection, draft summaries | Every review outcome |
| **Offboarding** | 3 | Checklists, scheduling, tracking | Final pay, anything legal |

Details: [product concept](docs/plan/product-concept.md) · [HR domain guide](docs/plan/hr-domain-guide.md).

## Repository layout

```
docs/
  plan/            master build plan, problem statement, product concept, HR guide
  research/        verified literature review + BibTeX (13 sources)
  architecture/    system design, HITL bounds, storage decisions, benchmarks
  api/             OpenAPI 3.0 specification
skills/            markdown skills + RAG knowledge — content, not code
src/hr_agents/
  models/          Pydantic v2 domain contracts
  services/        deterministic core: scorer, policy, priority, audit, documents
  skills/          skill loader → PydanticAI capabilities (on-demand)
  knowledge/       RAG: chunking, offline embeddings, namespace-scoped retriever
  tools/           least-privilege tool registry with audited execution
  api/             FastAPI ingestion, queue, application status
  db/              SQLAlchemy tables, async sessions
migrations/        Alembic (PostgreSQL 16)
tests/             731 tests, 92% coverage; ruff + mypy clean
web/               dashboard SPA (React 19 + Vite) — planned
landing/           public site (Next.js) — planned
```

## Documentation

- [Master build plan](docs/plan/master-build-plan.md) — the full checklist: phases, departments, progress
- [Remaining work](docs/plan/remaining-work.md) — MCP layer → dashboard → evals → ops → paper & release
- [Problem statement](docs/plan/problem-statement.md) — the systemic problem this exists to solve
- [Product concept](docs/plan/product-concept.md) — value, workspaces, dashboard UX, design system
- [HR domain guide](docs/plan/hr-domain-guide.md) — how HR actually works, Indonesian specifics, glossary
- [Literature review](docs/research/literature-review.md) — evidence base and design principles
- [System architecture](docs/architecture/system-architecture.md) — pipeline, HITL flows, Mermaid diagrams
- [HITL bounds](docs/architecture/hitl-bounds.md) — exact automation boundaries and anti-goals
- [Benchmarks](docs/architecture/benchmarks.md) — measured performance

## Roadmap

- [x] Literature review and verified citation base
- [x] Foundation: Python 3.14, uv, Docker Compose, CI
- [x] Contracts: Pydantic v2 models, OpenAPI 3.0, database schema
- [x] Deterministic core: scorer, policy engine, priority queue, audit chain
- [x] Ingestion API (measured 36,509 req/min in-process)
- [x] Skills system: markdown → on-demand PydanticAI capabilities, versioned + hashed
- [x] RAG engine: chunking, offline embeddings, namespace-scoped retrieval with citations
- [x] Tool registry: least-privilege scopes, audited execution (no shell tools, ever)
- [x] Agents: résumé deconstruction, code/portfolio evaluation, screening, feedback, policy Q&A
- [x] Decision layer: HITL boundaries enforced in code, fairness harness, append-only overrides
- [x] Recruitment API surface: documents, jobs, evaluations, overrides, feedback, scheduling
- [x] Departments: Onboarding, Records, Leave, Payroll prep, Compliance, Growth, Offboarding
- [ ] Dashboard SPA + PWA (monochrome design system)
- [ ] MCP layer + integrations (WhatsApp, Google Workspace, files, HRIS)
- [ ] Full eval suite (50 profiles + fairness pairs) and the technical paper
- [ ] Self-host setup wizard, observability, and public release (Apache-2.0)

## Technology

**Backend** Python 3.14 · FastAPI · Pydantic v2 · PydanticAI · PostgreSQL 16 + pgvector ·
Redis · MinIO · Docker · OpenTelemetry
**Dashboard** React 19 + Vite + Tailwind + shadcn/ui + PWA · **Public site** Next.js (SEO)

**Storage:** PostgreSQL is the production system of record — JSONB for profiles, pgvector
for embedding recall, ACID + row-level security for compliance. SQLite is only the
in-memory test engine. Rationale: [data storage decisions](docs/architecture/data-storage.md).

**Models:** provider-agnostic — local (Ollama), Anthropic, OpenAI, or a fully offline
`test` model for development and CI. The system runs end-to-end without any API keys.

## Work with the author

The software is free. If you want it running in your company without doing the technical
work — installation, WhatsApp/Google integration, customization, staff training —
the author offers freelance integration services.

> **Davin Akmal Yasha** · GitHub [@davinakmalyasha](https://github.com/davinakmalyasha) ·
> open an issue or reach out via the GitHub profile.

## License

[Apache-2.0](LICENSE) — free for every company, large or small.
