# Remaining Work — MCP layer to paper & release

Status snapshot: **2026-09-12**. Everything up to and including Phase 5 (multi-department
architecture: workspaces, RBAC, front door + Ask HR chat, tenancy + RLS, workspace-scoped tools,
cross-workspace handoff) is built and tested: **838 tests · 4 skipped (Postgres-only RLS) · ruff+mypy clean**.
The dashboard scaffold (Phase 6.0/6.0.1, W2a) has landed: tokens, shell, i18n, `/app` serving, CI job,
plus the workspace metadata API and the Ask HR chat UI with citations and handoff suggestions (W2b).

This file is the detailed checklist for everything **not yet done**, in build order. The master
plan (`master-build-plan.md`) keeps the high-level status; this file is the working document for
the phases that remain.

Legend: `[ ]` not started · `[~]` partially done · `[x]` done.

---

## 0. Known leftovers before the MCP layer (small, tracked here for completeness)

> **Progress (2026-09-12, PR #2):** W0 complete — ADR 0005 (sync domain layer),
> migration `0005_persistence`, `DbAuditChain` (hash chain in `audit_log`),
> Postgres adapters for every store, `HRAGENTS_STORE_BACKEND=postgres` wiring, a
> `postgres-adapters` CI job on pgvector, the `EvaluationJobHandler` (processing
> transition + step audits), the API→worker→evaluation seam test,
> `get_evaluation_breakdown` tool, and `scripts/verify_audit.py`.

- [x] **Postgres-backed persistence for the new surfaces.** Every in-memory store has a
      Postgres adapter behind the same interface, selected by `HRAGENTS_STORE_BACKEND`;
      the adapter suite runs on SQLite locally and PostgreSQL in CI.
- [x] **Audit-chain persistence.** The chain is persisted in `audit_log` with identical
      hash semantics (`DbAuditChain`, tamper-detection tested) and verified by
      `scripts/verify_audit.py` (exit 1 on the first broken sequence). The ops scheduler
      wires it into a cron in Phase 9.
- [x] **End-to-end pipeline test through the API.** `tests/api/test_pipeline_seam.py`:
      `POST /v1/applications` → queue → `Worker` + `EvaluationJobHandler` → extraction,
      scoring, decision → `evaluation.registered` → status, queue view, and evaluation
      endpoint all reflect the route.
- [x] **`get_evaluation_breakdown` agent tool.** Read-only, allowlisted to
      `feedback_writer`/`screening_coordinator`; serialization omits protected fields;
      denied-caller test included.
- [x] **Application status transitions on worker processing.** `EvaluationJobHandler`
      marks `processing` on claim, audits `worker.processing`/`worker.failed`/
      `worker.completed`, and evaluation registration syncs the terminal status.

---

## 1. MCP layer (Phase 7.4)

**Goal:** agents and external tools share one governed tool surface; destructive integrations stay
behind human approval.

### 1.1 MCP client manager
- [ ] Config schema: server name, transport (stdio/SSE), command/URL, auth env var names, enabled
      flag, tool allow/deny lists, timeout, retry policy
- [ ] Namespaced tool registration (`mcp.<server>.<tool>`) into the existing `ToolRegistry`, so
      least-privilege scoping and audit wrapping apply unchanged
- [ ] Health checks + graceful degradation: unreachable server ⇒ tools report `unavailable`, the
      agent falls back to built-in tools or escalates; never blocks the pipeline
- [ ] Redaction of server auth material in logs and API responses (`mask_secrets` contract)
- [ ] Config UI surface in Settings → Connections (Phase 6 dependency) with Test button

### 1.2 Server catalog (disabled by default)
- [ ] ATS connectors: Greenhouse, Lever (candidate/application sync, status reads)
- [ ] HRIS connectors: Talenta, Gadjah (employee master data, leave balances)
- [ ] Slack (notifications, approval pings — never decision-making)
- [ ] Calendar servers (Google/Microsoft busy lookup) as an alternative to the direct adapters
- [ ] Every catalog entry ships with: minimum scopes, a written data-flow note, and an "enable"
      runbook (what the operator must configure)

### 1.3 Approval hook for destructive MCP tools
- [ ] Classify tools as `read` / `write` / `destructive` in the registry (extend `ToolDefinition`)
- [ ] `destructive` ⇒ execution blocked; creates an approval through the shared Approval engine
      (`ApproverRole.MANAGER`/`HR_ADMIN` as configured) carrying a dry-run preview
- [ ] On approval: execute once, record the approval id in the audit payload; on rejection/expiry:
      no side effect, agent informed
- [ ] Tests: destructive tool cannot execute without a named human decision (negative tests first)

### 1.4 Expose `hragents-mcp` server
- [ ] Read tools: queue, application status, evaluation summary, pending approvals, leave balances
- [ ] Write tools (approval-gated): create application from external ATS, request document, open
      onboarding plan — **never** payroll, erasure, or rejection execution
- [ ] Auth: API key scopes, per-tool permission map, audit on every call
- [ ] Packaged entry point (`hragents-mcp` console script) + docs page with Claude Desktop /
      other-client config examples
- [ ] Contract tests running against the server itself (MCP client ↔ server round-trip)

**Exit criteria:** an agent can use an external MCP tool end-to-end; a destructive tool is
unexecutable without human approval; the `hragents-mcp` server passes contract tests and is
documented.

---

## 2. Web dashboard + PWA (Phase 6)

**Goal:** the "solo HR" experience — attention-first home, three-room workspaces, mobile-first.

### 2.1 Project setup & design system
- [x] `web/` — Vite + React 19 + TypeScript, Tailwind, shadcn/ui themed to the locked tokens
- [x] TanStack Query (server state) + Zustand (workspace/UI state)
- [x] API client generated from the live OpenAPI document (`scripts/export_openapi.py` →
      `docs/api/openapi.json`, `docs/api/openapi.yaml` kept as legacy docs)
- [x] ESLint + Prettier + `tsc --noEmit` CI gate (`web` job); static build served by FastAPI at `/app`
- [x] Design tokens exactly per `product-concept.md` §7 (cool-gray ramp, single accent `#2563EB`,
      amber/red/green ≤5% pixels with icon+label, dark mode = token swap, hex-literal guard test)
- [x] Inter + JetBrains Mono, 12–30 scale, weights 400/500/600 (self-hosted, offline-safe)
- [~] Component kit: base shadcn/ui set + StatusBadge/ScoreBar/EmptyState; command palette wiring next

### 2.2 Shell, auth, i18n
- [~] App shell: sidebar workspaces, topbar, responsive layout; three-room layout component
      (Board / Queue / Chat) with placeholders (real surfaces land per workspace)
- [ ] Auth screens: login, session handling, password reset (API keys for service accounts)
- [x] i18n from day one: English + Bahasa Indonesia locale files, language switcher, key-parity test
- [ ] Accessibility: WCAG AA, keyboard navigation, reduced motion, icon+label on every status color
      (baseline in place: focus rings, reduced-motion CSS, icon+label StatusBadge)
- [ ] Mobile-first check at 390px (queues, approvals, chat)

### 2.3 Attention-first home
- [x] "Needs you today" wired to real queues: overdue approvals, overdue tasks, open handoffs
      (role-scoped 403s degrade to empty sections rather than error walls)
- [x] "Watching" section: pending approvals within SLA and open tasks
- [x] No vanity metrics; every item deep-links to the workspace queue (`/w/{id}?room=queue`)

### 2.4 Recruitment workspace
- [ ] Pipeline board (kanban: received → screened → interview → offer) with dnd-kit, status
      updates through the API
- [ ] Candidate detail: score breakdown, evidence references, timeline, flags, override history
- [ ] Review queue for HITL: soft-rejection sign-off, anomalies, calendar constraints — uses the
      override endpoint with reason codes
- [ ] Scheduling view: proposals, auto vs. needs-approval, slot confirmation, reschedules
- [ ] Batch import UI (XLSX/CSV + drag-drop CVs) with progress; documents upload wired to
      `POST /v1/documents`
- [ ] Job management: create/edit jobs, status lifecycle, dimension weight editor (with the
      sum-to-1.0 validation surfaced inline)

### 2.5 Department workspaces (Wave-1 surfaces)
- [~] Ask HR: chat with citations and handoff suggestions done; progressive SSE streaming and
      tool-call visibility remain (see polish backlog)
- [ ] Onboarding workspace: checklists, document collection status, waive with reason
- [ ] Records workspace: employee directory, document vault, expiry alerts, org chart
- [ ] Leave workspace: policies, balances, request calendar, approval queue
- [ ] Payroll workspace: run assembly, anomaly review, sign-off submission, XLSX packet download
      (with the "no payments executed" notice rendered in the UI)
- [ ] Growth workspace: cycles, form collection, draft → finalize editor, goals
- [ ] Offboarding workspace: exit checklists, asset clearance, handover notes, final-pay link
- [ ] Compliance workspace: consent registry, retention scan/purge, erasure workflow, breach
      checklist, audit-chain verifier with visible integrity result
- [ ] Audit viewer: searchable entries, chain verification badge, export

### 2.6 PWA
- [ ] `vite-plugin-pwa`: manifest, service worker, offline shell
- [ ] Install prompt + push notifications (approvals, SLAs, interview confirmations)
- [ ] Lighthouse PWA + mobile performance pass (target ≥ 90 PWA score)

**Exit criteria:** a solo HR user can run a full ready-to-hire cycle, an onboarding, a leave
approval, a payroll prep + sign-off, and an offboarding end-to-end without touching the API.

---

## 3. Landing site (Phase 10 early)

- [ ] `landing/` — Next.js SEO site (separate deployment; not part of the self-host product)
- [ ] Pages: HR automation Indonesia, open-source ATS alternative, payroll prep explainer
- [ ] Docs section (rendered from `docs/`), changelog, demo video embed
- [ ] "Work with me" page: freelance integration/consulting offer with contact form
- [ ] Analytics + OG images; no dark patterns, no fake testimonials

---

## 4. Evaluations expansion (Phase 4.4 completion)

**Goal:** the paper's measured results. Current live run: 5 cases, 100% assertions (MiMo V2.5 via
CommandCode). Expand to the full dataset and record honest latency/cost.

### 4.1 Dataset (50 profiles)
- [ ] 18 engineering profiles (backend, frontend, data, mobile, DevOps) — EN/ID mixed
- [ ] 32 non-IT profiles (finance, operations, sales, admin, customer support) to prove the
      extraction layer generalizes beyond engineering
- [ ] Formats: PDF + Markdown + JSON per profile class (fixtures committed, sizes representative)
- [ ] The 4 name-swap fairness pairs embedded in the set (scoring invariance, not just harness)

### 4.2 Edge cases (~15)
- [ ] Date overlap / unexplained gap; career change; overqualified; freelance history
- [ ] Fake certification; scanned (image-only) PDF; oversize document; malformed JSON export
- [ ] 2 prompt-injection CVs (whitespace + multi-line variants)
- [ ] Ghost-job mismatch: profile far below job requirements

### 4.3 Suites to add
- [ ] Resume extraction: structural assertions across all 50 + edge cases
- [ ] Feedback faithfulness: grounding validator against stored evaluations (live model)
- [ ] Policy regression: threshold routing table (pure, fast, runs offline)
- [ ] Fairness: distribution monitoring on the real scoring path (not just counterfactuals)
- [ ] Keep the honest latency section in `benchmarks.md` updated (p50/p95, per-model)

**Exit criteria:** one command runs the full suite offline and live; results table committed with
latency, costs, and failure modes documented.

---

## 5. Deployment & operations (Phase 9)

**Goal:** one command to self-host, safe defaults, zero required external services.

- [ ] Setup wizard (CLI + first-run web flow): admin account, organization profile, provider
      connect-or-skip, starter templates (onboarding/offboarding leave policies, rate tables)
- [ ] One-command self-host: `docker compose up` with postgres+pgvector, redis, minio, mailpit;
      migrations auto-run; `/healthz` + readiness endpoint
- [ ] Provider settings UI with health badges, env-lock indicators, masked secrets (Settings →
      Connections)
- [ ] Local-model mode (Ollama): fully offline operation, documented model floor (size/quality)
- [ ] Backup/restore docs + scripts (pg_dump, document storage, chain verification after restore)
- [ ] Region recipes: Jakarta / Singapore deployment notes; Cloudflare Tunnel guide for webhooks
- [ ] Security hardening: key management, secrets rotation, rate limits, upload scanning hook,
      pen-test checklist, dependency scanning in CI
- [ ] Observability: OTel traces (API → pipeline → agents), Prometheus metrics, Grafana dashboard,
      LLM cost tracking (token accounting per model)
- [ ] Data governance: full export, deletion procedures, DPA template, subprocessor list
- [ ] Scheduled jobs: retention sweep, approval SLA escalation, breach overdue alerts, review
      reminders, contract expiry watchers (all call existing engines; needs a scheduler runner)
- [ ] Managed cloud SaaS + billing — **deferred until proven demand** (`[-]` in master plan)
- [ ] Dedicated instance (BYOC) recipes — only if requested
- [ ] Office Connector folder-sync agent — only if demanded

**Exit criteria:** a new operator with Docker Desktop installed is running a working instance in
under 10 minutes, with zero cloud keys required (hash embeddings + manual providers).

---

## 6. Paper, docs & release (Phase 10)

- [ ] Paper: recruitment deep-dive (deterministic scoring + HITL bounds) plus the "HR department of
      one" platform framing; honest limitations section
- [ ] Measured results: ingestion throughput (36,509 req/min measured), eval scores, fairness-audit
      results, live-model latency, cost per application
- [ ] README: 5-minute quickstart, demo dataset, screenshots/GIF, architecture diagram
- [ ] README "Work with the author / freelance integration" finalized (services, contact, scope)
- [ ] Demo video / GIF walkthrough (2–3 minutes: ingest → review → override → schedule)
- [ ] API docs site (OpenAPI rendered) + operator runbooks (backup, upgrade, provider failures,
      incident response with the breach workflow)
- [x] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue templates, security policy, ADRs, release
      process (landed early with the repo-infrastructure work — see `master-build-plan.md` Phase 1)
- [ ] Docs site (mkdocs-material + GitHub Pages), versioned with releases
- [ ] Container image on GHCR: multi-arch, Trivy-scanned (needs `Dockerfile`, Phase 9)
- [ ] SBOM + build provenance attestations attached to releases
- [ ] PyPI publishing — only if a library use case appears (currently deferred)
- [ ] GitHub social preview image + demo assets (screenshots/GIF)
- [ ] Immutable releases for tags, once the release flow has settled
- [ ] Public release: GitHub tag, release notes, Apache-2.0 confirmed, reproducible build steps

**Exit criteria:** a stranger can evaluate the product from the README alone, reproduce the
benchmarks, and self-host without contacting the author.

---

## Suggested execution order

| Order | Workstream | Depends on | Why this order |
|---|---|---|---|
| 1 | Postgres persistence for new surfaces + audit sink | — | Everything after (MCP, UI, ops) gets safer with durable state |
| 2 | MCP layer (client manager → approval hook → server) | 1 | Unlocks ATS/HRIS integrations the market expects |
| 3 | Dashboard + PWA (`web/`) | 1 | The product's adoption surface; needs stable APIs |
| 4 | Evals expansion | — (parallel) | Runs offline; feeds the paper while UI is built |
| 5 | Ops hardening (wizard, compose, observability) | 1, 3 | Must be stable before public release |
| 6 | Landing + paper + release | 3, 4, 5 | Release last; paper cites measured results |

### Risk notes

- **MCP destructive-tool safety** is the highest-risk area: approval hook must land *with* the
  manager, not after. Negative tests are the acceptance gate.
- **LLM latency** (mean ~82 s live) shapes the UI: progress states and "watching" sections are
  required before launch; do not hide processing time.
- **Coverage floor**: keep ≥ 90% on `src/hr_agents`; new UI work must not dilute the invariant
  suite (scoring, policy, fairness, audit chain, payroll gates stay at 100% branch).
- **No scope creep into payment execution, biometric hardware, or accounting** — see
  `master-build-plan.md` Appendix A.
