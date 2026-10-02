# HRAgents — A Virtual HR Team for the HR Department of One

> One HR generalist, ten jobs, no time. HRAgents gives them a team: agents that read,
> chase, calculate, and draft — while humans keep every decision that matters.

**Free and open source (Apache-2.0).** Self-host it, inspect it, modify it. The author
offers paid integration services for companies that want it running without the
technical work — see [Work with the author](#work-with-the-author).

[![CI](https://github.com/davinakmalyasha/HRAgents/actions/workflows/ci.yml/badge.svg)](https://github.com/davinakmalyasha/HRAgents/actions/workflows/ci.yml)
[![CodeQL](https://github.com/davinakmalyasha/HRAgents/actions/workflows/codeql.yml/badge.svg)](https://github.com/davinakmalyasha/HRAgents/actions/workflows/codeql.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)

**Status:** active development. The platform core, all five agents, the recruitment
API surface, and all Wave-1 department engines are operational and wired into a
running worker (1263 tests, coverage enforced at 90% in CI). The hiring dashboard
workspaces run end to end. Still open: the remaining dashboard workspaces,
authentication screens, and the MCP layer. No public release yet - see the
[remaining work plan](docs/plan/remaining-work.md).

---

## Quickstart

Docker Desktop, five minutes, no cloud keys:

```bash
git clone https://github.com/davinakmalyasha/HRAgents
cd HRAgents
docker compose up --build -d
```

Then open **<http://localhost:8000/app>**. Nine containers come up: postgres, redis,
minio, mailpit, `migrate`, the API, plus a **worker** that evaluates submitted
applications, a **scheduler** for the daily department chores, and a **messaging**
process that drains the outbound queue. Migrations run automatically before the
API serves.

Verify the pipeline is actually running before you trust anything you see:

```bash
curl -s localhost:8000/readyz | python -m json.tool   # queue + skills must be "ok"
curl -s localhost:8000/metrics | grep stuck_queued   # non-zero = no worker draining
```

**Nothing leaves your machine.** Mailpit catches all email, messaging is
sandboxed, and the LLM defaults to the offline `test` model. To use a real model,
set `HRAGENTS_LLM_MODEL` and the matching provider config — see
[`.env.example`](.env.example).

Logs: `docker compose logs -f api worker`. Stop: `docker compose down`.
Data survives; `docker compose down -v` deletes it.

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

A submitted application is published to a queue; a worker claims it and runs the
full pipeline. Every step is auditable.

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

> **Known limits, stated plainly.** The four scoring dimensions are calibrated for
> engineering roles, so a non-technical candidate is systematically under-scored —
> generalization to other job families is the top planned change. The knowledge
> corpus behind "Ask HR" is a seed set, not an Indonesian HR library. And only the
> `consent` entity has a working data-erasure handler today; erasing a candidate
> record is reported as `not_executed` rather than falsely claiming success. See
> [remaining work](docs/plan/remaining-work.md) for the full picture.

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

## The plan: one HR person, nine workspaces

| Workspace | Wave | Agents do | Humans gate |
|---|---|---|---|
| **Hiring** | 1 (building) | Extract, score, coordinate, draft | Every rejection, every offer |
| **Ask HR** (front door) | 1 | Intent routing, cited policy Q&A | Anything consequential |
| **Compliance** | 1-2 | Consent registry, retention, erasure, breach workflow | Identity verification, every erasure, every purge |
| **Onboarding** | 1-2 | Checklists, document chasing | Contracts, signatures |
| **People** | 2 | Records, expiry alerts, retention | Corrections, sensitive fields |
| **Leave** | 2 | Balance math, policy Q&A, routing | Every approval |
| **Payroll** | 3 | Assemble, calculate, flag, export | **Everything - no payment is ever executed** |
| **Growth** | 3 | Reminders, collection, draft summaries | Every review outcome |
| **Offboarding** | 3 | Checklists, scheduling, tracking | Final pay, anything legal |

Details: [product concept](docs/plan/product-concept.md) · [HR domain guide](docs/plan/hr-domain-guide.md).

## Repository layout

```
docs/
  plan/            master build plan, problem statement, product concept, HR guide
  research/        verified literature review + BibTeX (13 sources)
  architecture/    system design, HITL bounds, storage decisions, benchmarks
  api/             OpenAPI 3.1 specification (generated from the live app)
skills/            markdown skills + RAG knowledge — content, not code
scripts/           run_worker (the pipeline), run_scheduler, run_messaging, backup, checks
src/hr_agents/
  agentset.py      composition root: builds every agent from the skills library
  queue.py         resolves the live queue backend both the API and worker share
  models/          Pydantic v2 domain contracts
  services/        deterministic core: scorer, policy, priority, audit, documents
  skills/          skill loader → PydanticAI capabilities (on-demand)
  knowledge/       RAG: chunking, offline embeddings, namespace-scoped retriever
  tools/           least-privilege tool registry with audited execution
  api/             FastAPI ingestion, queue, application status, /metrics, /readyz
  db/              SQLAlchemy tables, async sessions
migrations/        Alembic (PostgreSQL 16)
tests/             test suite; ruff + mypy clean
web/               dashboard SPA (React 19 + Vite + Tailwind + shadcn/ui)
landing/           public site (Next.js) — planned
docker/            Postgres init scripts (demote the superuser so RLS applies)
```

## Documentation

- [Master build plan](docs/plan/master-build-plan.md) — the full checklist: phases, departments, progress
- [Remaining work](docs/plan/remaining-work.md) — MCP layer → dashboard → evals → ops → paper & release
- [Release process](docs/plan/release-process.md) — versioning, branching, how releases are cut
- [Architecture decisions (ADRs)](docs/adr/README.md) — the reasoning behind the locked choices
- [Problem statement](docs/plan/problem-statement.md) — the systemic problem this exists to solve
- [Product concept](docs/plan/product-concept.md) — value, workspaces, dashboard UX, design system
- [HR domain guide](docs/plan/hr-domain-guide.md) — how HR actually works, Indonesian specifics, glossary
- [Literature review](docs/research/literature-review.md) — evidence base and design principles
- [System architecture](docs/architecture/system-architecture.md) — pipeline, HITL flows, Mermaid diagrams
- [Deployment & operations](docs/deployment.md) — self-host with Docker Compose, backups, runbooks
- [HITL bounds](docs/architecture/hitl-bounds.md) — exact automation boundaries and anti-goals
- [Benchmarks](docs/architecture/benchmarks.md) — measured performance

## Roadmap

- [x] Literature review and verified citation base
- [x] Foundation: Python 3.14, uv, Docker Compose, CI
- [x] Contracts: Pydantic v2 models, OpenAPI 3.1, database schema
- [x] Deterministic core: scorer, policy engine, priority queue, audit chain
- [x] Ingestion API (measured 36,509 req/min in-process)
- [x] Skills system: markdown → on-demand PydanticAI capabilities, versioned + hashed
- [x] RAG engine: chunking, offline embeddings, namespace-scoped retrieval with citations
- [x] Tool registry: least-privilege scopes, audited execution (no shell tools, ever)
- [x] Agents: résumé deconstruction, code/portfolio evaluation, screening, feedback, policy Q&A
- [x] Decision layer: HITL boundaries enforced in code, fairness harness, append-only overrides
- [x] Recruitment API surface: documents, jobs, evaluations, overrides, feedback, scheduling
- [x] Departments: Onboarding, Records, Leave, Payroll prep, Compliance, Growth, Offboarding
- [x] Multi-department architecture: workspaces, RBAC, front door chat, tenant RLS, handoffs
- [x] Evaluation worker: the API publishes, a worker claims and runs the pipeline end to end
- [x] Verified rate tables: enter, verify with a source, and unblock payroll compute
- [x] Operability: `/readyz` per-dependency, `/metrics` with a stuck-queue canary
- [~] Dashboard SPA + PWA (monochrome design system) — chat, attention home, hiring board,
      review queue, batch import, onboarding, records, offline shell; approvals decision UI,
      XLSX, auth screens, and push remain
- [ ] Scoring generalized beyond engineering (job-family dimension templates)
- [ ] Indonesian statutory knowledge base + compliance calendar
- [ ] MCP layer + integrations (WhatsApp Meta Cloud, Google Workspace, files, HRIS)
- [ ] Full eval suite (50 profiles + fairness pairs) and the technical paper
- [ ] Self-host setup wizard, demo dataset, and public release (Apache-2.0)

## Technology

**Backend** Python 3.14 · FastAPI · Pydantic v2 · PydanticAI · PostgreSQL 16 · Redis ·
Docker · MinIO (reserved for object storage) · Dashboards: React 19 + Vite + Tailwind +
shadcn/ui + PWA

**Storage:** PostgreSQL is the production system of record — JSONB for profiles and
document bytes, ACID + row-level security for compliance. SQLite is only the in-memory
test engine. Rationale: [data storage decisions](docs/architecture/data-storage.md).
Documents currently live in Postgres (`candidate_documents`, 10 MiB cap) rather than
S3/MinIO; the `storage` provider exists but is not yet wired to the document path.

**Models:** provider-agnostic — local (Ollama), Anthropic, OpenAI, or a fully offline
`test` model for development and CI. The system runs end-to-end without any API keys.

**Observability:** `/readyz` reports each dependency (database, messaging, audit,
**queue**, **skills**) and returns 503 when the product cannot actually work;
`/metrics` exposes Prometheus text, including
`hragents_applications_stuck_queued` — the canary for "submissions are being
accepted but nothing is evaluating them".

**Dashboard (development):**

```bash
cd web
npm ci
npm run dev      # http://localhost:5173/app/ — proxies /v1 to localhost:8000
```

The static build (`npm run build`) is served by FastAPI at `/app` when `web/dist`
exists; the checked-in OpenAPI spec (`docs/api/openapi.json`) is regenerated with
`uv run python scripts/export_openapi.py` and the typed client with
`npm run api:generate`.

## Work with the author

The software is free. If you want it running in your company without doing the technical
work — installation, WhatsApp/Google integration, customization, staff training —
the author offers freelance integration services.

> **Davin Akmal Yasha** · GitHub [@davinakmalyasha](https://github.com/davinakmalyasha) ·
> open an issue or reach out via the GitHub profile.

## Contributing

Contributions are welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) first. The short
version: trunk-based branches, Conventional Commits with DCO sign-off, and a green
`uv run python scripts/check.py` before opening a PR. Security reports go through the
[private advisory flow](SECURITY.md); everyone follows the
[Code of Conduct](CODE_OF_CONDUCT.md). If you use HRAgents in academic work, cite it via
[CITATION.cff](CITATION.cff).

## License

[Apache-2.0](LICENSE) — free for every company, large or small.
