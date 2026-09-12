# HRAgents — Master Build Plan

**Purpose:** the single source of truth for everything to build. Nothing is out of scope — items are
ordered by dependency, and checkboxes track reality so nothing is missed or forgotten.

**Legend:** `[ ]` not started · `[~]` in progress · `[x]` done · `[-]` explicitly deferred

**Update rule:** every work session ends by updating this file. An item is `[x]` only when its tests
(and docs where relevant) exist and pass.

---

## 0. Locked decisions

| Decision | Choice |
|---|---|
| Persona | Solo HR (1–3 people) at an Indonesian SME doing everything |
| Product | A virtual HR team behind one HR person; recruitment is the deep build, other departments are packs |
| Deployment | Self-hostable open source **and** managed cloud SaaS — one codebase, tenant-aware from day one |
| Stack | Python 3.14 · FastAPI · Pydantic v2 · PydanticAI · PostgreSQL 16 + pgvector · Redis · MinIO · Docker |
| Dashboard | React 19 + Vite + TypeScript + Tailwind + shadcn/ui + TanStack Query + Zustand + dnd-kit + PWA (`web/`) |
| Public site | Next.js App Router — SEO pages, docs, demo, freelance showcase (`landing/`), deployed separately; not part of the self-hosted product |
| Design language | Monochrome cool gray, light default (dark mode = token swap); one accent `#2563EB` for interactive; status colors amber/red/green ≤5% of pixels with icon+label; Inter + JetBrains Mono; attention-first home ("Needs you today" / "Watching"); three rooms per workspace (Board / Queue / Chat) |
| Backend language | Python-only. Rust/Go hotspot extraction only if profiling ever demands it; core rewrite rejected (bottleneck is LLM inference, not CPU) |
| Agent architecture | Agents extract + communicate only; deterministic core decides; humans gate every rejection |
| Audit | Hash-chained append-only log; every decision reconstructible |
| Tools | Typed, least-privilege registry. **No shell/`run_command` tools — ever** |
| Providers | Every external dependency is a capability with interchangeable providers (LLM, email, WhatsApp, calendar, storage, embeddings, vector store, queue). One file per provider; config via env/wizard/UI; UI wins, env can lock. See `docs/architecture/providers.md` |
| Queue | Provider pattern: `redis` (default, included in compose) · `postgres` (minimal installs) · `memory` (tests). One conformance suite across backends |
| Models | Provider-agnostic: local (Ollama) / Anthropic / OpenAI / Gemini / OpenRouter / Groq / any OpenAI-compatible base URL / offline `test` model |
| UI language | English + Bahasa Indonesia from first release |
| RAG policy | Retrieval for recall and Q&A only — never used to compute scores |
| Fairness | CI counterfactual name-swap invariance tests + per-job score-distribution monitoring |
| Retention | Default 24 months then auto-anonymize; configurable per tenant (longer requires consent) |
| Thresholds | Auto-schedule `S ≥ 0.85 ∧ σ ≤ 0.05`; rejection sign-off required for `S ≥ 0.70` |
| License | Apache-2.0 — fully open for every company (not just big ones). Author offers paid freelance integration/setup services; contact in README |

---

## Business & distribution model (locked)

- The software is free and open source (Apache-2.0). Any company — SME or enterprise — can
  self-host it at software cost zero.
- Income model: freelance integration/setup services for companies that want it running without
  doing the technical work themselves (install, configure, connect WhatsApp/Google, train staff).
- No SaaS billing, no paywalled features, no license gating. Managed hosting is a later option
  only if real demand appears (Phase 9, deferred).
- Adoption priority therefore: 5-minute install, setup wizard, excellent docs, demo dataset
  that proves value before any integration work.
- The author's name, product name, and freelance contact are surfaced in README and docs.

---

## Status summary

| Phase | Status |
|---|---|
| 0. Research & evidence | Done |
| 1. Foundation & infrastructure | Done |
| 2. Contracts & data model | Done |
| 3. Deterministic core & pipeline | Done |
| 4. Platform capabilities (skills, RAG, tools, providers, agents, evals) | **In progress** — skills ✅, RAG ✅, tools ✅, providers ✅, agents ✅ (5/5), pipeline ✅, recruitment API surface ✅, evals 🔄 |
| 5. Multi-department architecture (workspaces, front door, RBAC, tenancy) | **Done** — workspaces ✅, RBAC ✅, front door + Ask HR chat ✅, tenancy + RLS ✅, workspace-scoped tools ✅, cross-workspace handoff ✅ (conversation-store Postgres adapter lands with Phase 6) |
| 6. Web app + PWA | Not started |
| 7. Integrations (messaging, Google, files, MCP) | Not started |
| 8. Departments (onboarding, records, leave, payroll prep, performance, offboarding) | **Done (Wave 1 engines)** — onboarding ✅, records ✅, leave ✅, payroll prep ✅, compliance ✅, growth ✅, offboarding ✅ |
| 9. Deployment & compliance | Not started |
| 10. Paper, docs & publication | Not started |

> **Remaining work, MCP layer → paper & release:** `docs/plan/remaining-work.md` — detailed
> checklists, exit criteria, suggested order, and risk notes for everything still open.

---

## Phase 0 — Research & evidence `DONE`

- [x] Literature review with 13 verified sources (`docs/research/literature-review.md`)
- [x] BibTeX bibliography with verification notes (`docs/research/sources.bib`)
- [x] Evidence → design principle mapping (P1–P10)
- [ ] Indonesian labor-law knowledge base (UU Ketenagakerjaan, BPJS, THR, PPh 21, WLKP) — Phase 8
- [ ] Domestic hiring-funnel field notes / validation interviews — Phase 10

## Phase 1 — Foundation & infrastructure `DONE`

- [x] uv project, Python 3.14, dependency groups (dev/prod)
- [x] Docker Compose: Postgres 16 + pgvector, Redis 7, MinIO, Mailpit
- [x] Configuration via pydantic-settings, structured logging, OTel dependencies
- [x] CI workflow (ruff, format, mypy, pytest)
- [x] FastAPI app factory + `/healthz`
- [x] `.gitignore`, `.env.example`, repo layout
- [x] CI hardening: `quality` · `migrations` (pgvector upgrade/drift/downgrade) · `windows` ·
      `secrets` (gitleaks history scan); actions SHA-pinned; coverage floor 90%
- [x] CodeQL, Dependabot (uv + actions), release-please, release-artifacts workflow
- [x] Community health: `CONTRIBUTING`, `SECURITY`, `CODE_OF_CONDUCT`, issue forms, PR template,
      `CODEOWNERS`
- [x] pre-commit hooks (ruff, formatting, private-key detection) + `scripts/check.py`
- [x] ADRs (`docs/adr/`), release process (`docs/plan/release-process.md`), `CITATION.cff`,
      `AGENTS.md`

## Phase 2 — Contracts & data model `DONE`

- [x] Pydantic v2 domain models: candidate, evaluation, job, policy, scheduling, audit, messaging, common
- [x] `aggregate_runs` (k=3, σ) and `ScoreVector.weighted_mean`
- [x] SQLAlchemy tables + Alembic `0001_initial` (9 tables, indexes, cascades)
- [x] OpenAPI 3.0.3 spec (12 paths, 24 schemas)
- [x] Architecture docs: system, HITL bounds, data/storage rationale, benchmarks
- [x] Mermaid diagrams: pipeline, HITL sequence, lifecycle states, ER

## Phase 3 — Deterministic core & pipeline `DONE`

- [x] Vector scorer `S ∈ [0,1]^4` with alias normalization, tenure math, rationales, evidence refs
- [x] Policy engine: consent halt → anomaly → calendar → auto-schedule → soft-rejection → auto-reject
- [x] Priority ranker `P = α·S̄ + β·e^(−λΔt) + γ·A − δ·R`
- [x] Hash-chained audit log with tamper detection
- [x] Document ingestion: hashing, PDF/text extraction, PII redaction (email, NIK, phone)
- [x] Application store with exactly-once idempotency + conflict semantics
- [x] API routers: submit, batch (≤500), status+timeline, queue; RFC 7807 errors; API-key auth
- [x] Test suite (83 tests, 97% coverage) + ingestion benchmark (36,509 req/min measured)

---

## Phase 4 — Platform capabilities `IN PROGRESS`

### 4.1 Skills system (markdown → capabilities) `DONE`
- [x] `SkillManifest` model: id, name, description, version, department, agents allowlist, tags
- [x] Loader: discover `skills/**/SKILL.md`, parse YAML frontmatter, validate, hash
- [x] Capability builder: markdown → PydanticAI `Capability(defer_loading=True)`
- [x] Knowledge doc model + loader (`knowledge/**/*.md`, namespace-scoped)
- [x] Skill registry: lookup by agent/department/namespace, deterministic library fingerprint, audit refs
- [x] Skills content (Wave 1):
  - [x] `skills/recruiting/screening/SKILL.md` (candidate communication runbook)
  - [x] `skills/recruiting/evaluation/SKILL.md` + `knowledge/backend-rubric.md` + `ai-engineer-rubric.md`
  - [x] `skills/recruiting/feedback/SKILL.md` + `knowledge/feedback-template.md`
  - [x] `skills/platform/compliance/SKILL.md` + `knowledge/uu-pdp-summary.md`
  - [x] `skills/platform/knowledge/SKILL.md` + company-profile template
- [x] Skills authoring guide (`skills/README.md`)
- [ ] Skills editor UI — Phase 6
- [x] Tests: 34 tests covering format validation, duplicates, department/domain layout, hashing, registry, capability building

### 4.2 Knowledge / RAG engine `DONE` (cloud adapters deferred to Phase 7)
- [x] Heading-aware markdown chunker with source spans, merge/split rules, deterministic ids
- [x] Embedding providers: protocol + deterministic offline signed-hash provider (default; runs without keys)
- [ ] API-backed embedding provider (OpenAI/Voyage/Ollama) — Phase 7 via provider layer
- [ ] pgvector store adapter + index migration — Phase 7 via provider layer (same retriever interface)
- [x] Retriever: hybrid vector + keyword scoring, namespace scoping with permission errors, citations
- [x] `search_knowledge` tool wired to retriever with mandatory citations (built in 4.3)
- [~] Knowledge upload UI (upload docs → chunk → embed → index) — Phase 6; skills loader covers current ingestion
- [~] Retrieval evals: namespace-leak tests done; recall@k fixtures with real embeddings later

### 4.3 Tool registry & tools `IN PROGRESS`
- [x] Registry with per-agent scoping (least-privilege allowlists, no implicit access)
- [x] Tool call audit wrapper (actor=agent, tool name, argument hash — raw args never logged)
- [x] Tools:
  - [x] `canonicalize_skill` (alias normalization, deterministic)
  - [x] `search_knowledge` (namespace-scoped RAG, citations mandatory, limit caps)
  - [x] `github_profile`, `repo_metrics` (fixture + real HTTP client behind one protocol)
  - [x] `analyze_repo_ast`, `detect_frameworks` (radon + lizard, sandboxed to analysis root)
  - [x] `lookup_publication` (Crossref-style index; live adapter later), `verify_credential` (registry snapshot)
  - [x] `get_candidate_profile`, `capture_consent`, `record_availability`, `escalate_to_human`
  - [x] `get_evaluation_breakdown` — read-only tool allowlisted to `feedback_writer`/`screening_coordinator`
- [x] Tool permission tests (denied calls audited, cross-agent isolation verified)
- [ ] Sandbox/dry-run default for external tools — Phase 7 external integrations

### 4.4 Agents (PydanticAI) `IN PROGRESS`
- [x] Runtime: provider-driven model resolution (test/ollama/openai-compatible/anthropic/commandcode), limits, per-provider structured output (prompted JSON for open-model endpoints)
- [x] `AgentDeps` ports (tool registry, audit, scoped namespaces — injectable for tests)
- [x] `InjectionGuard`: deterministic detectors, invisible-char stripping, line redaction, full-text multi-line scanning
- [x] `ResumeDeconstructor` → `CandidateProfile` (guard-first, skill-composed instructions, skill audit refs)
- [x] `CodePortfolioEvaluator` → `PortfolioEvidence` (repos, complexity, frameworks, publications, credentials; summary recomputed deterministically; forks excluded)
- [x] `ScreeningCoordinator` → `ScreeningReply` (state machine enforcement, banned-phrase/protected-topic validation, escalation rules)
- [x] `PolicyAssistant` → `PolicyAnswer` (cite-or-escalate enforcement)
- [x] `FeedbackWriter` + deterministic grounding validator (thresholds, duplicates, protected attributes EN/ID)
- [~] Agent evals (Pydantic Evals) — `evals/resume_extraction.py` + `scripts/run_evals.py`:
  - [x] Injection safety cases (prompt injection, invisible chars)
  - [x] Structural/safety evaluators (schema round-trip, guard expectations, sanitization)
  - [x] **Live model run passing: 5/5 cases, 100% assertions on MiMo V2.5 via Command Code (ZDR on)** — results in `docs/architecture/benchmarks.md` §4
  - [ ] 50-profile dataset: 18 engineering + 32 non-IT, EN/ID mixed, PDF+MD+JSON variants
  - [ ] Edge cases (~15): name-swap fairness pairs, date overlap/gap, fake certification, scanned PDF, oversize, career change, overqualified
  - [ ] Feedback faithfulness live-model suite
  - [ ] Policy regression suite (threshold routing table)

### 4.5 Pipeline wiring `IN PROGRESS`
- [x] `ApplicationPipeline`: received → guard → extract (k runs) → score → aggregate → policy → route → persist, fully audited
- [x] `Worker` (claim/ack/nack/dead-letter) over any queue backend, bounded attempts
- [x] Fairness harness: counterfactual name/city-swap invariance audit + summary (violation injection test proves detection)
- [x] Storage port (`InMemoryStorage` now; Postgres adapter later)
- [x] **Recruitment API surface** (`services/recruiting.py` + 5 routers, 15 endpoints): document upload with hashing/size gate, jobs CRUD + guarded lifecycle, evaluation read (`/v1/applications/{id}/evaluation`), append-only HITL overrides with audit receipts and role enforcement, feedback reports (stored agent report or deterministic EN/ID synthesis), scheduling proposals gated by the policy engine with an availability registry
- [x] Application store: status sync from evaluation results and human overrides, candidate lookup
- [ ] Orchestrator as pydantic-graph state machine (current: explicit async pipeline; graph upgrade when retries/checkpoints demand)
- [x] HITL overrides persisted to Postgres (append-only `evaluation_overrides` table + `DbEvaluationService`)
- [x] Audit chain persistence to Postgres (migration `0005` + `DbAuditChain`; `scripts/verify_audit.py`; cron wiring in Phase 9)
- [x] End-to-end integration test through the API: submit → worker → evaluation → queue (`tests/api/test_pipeline_seam.py`)

### 4.6 Provider layer (adaptive integrations) `IN PROGRESS`
- [x] Spec written: `docs/architecture/providers.md`
- [x] `providers/base.py` — `Capability`, `ProviderConfig` (SecretStr support), `ProviderSpec`, `ProviderHealth`
- [x] `providers/registry.py` — registration, discovery, resolution, explicit fallback chains (zero-config providers resolve first)
- [x] Queue providers: `memory` + `redis` + `postgres` with one conformance suite
- [x] LLM providers: `test` + `ollama` + `openai_compatible` + `anthropic` + `commandcode` (ZDR default, MiMo default)
- [x] Email providers: `smtp` + `resend` (send) · `imap_poll` + `resend_webhook` (receive)
- [x] Messaging providers: `whatsapp.manual_links` (always-on degraded) + `whatsapp.meta_cloud`
- [x] Calendar providers: `calendar.manual_slots` (+ ICS) + `calendar.google`
- [x] Storage providers: `storage.local_disk` + `storage.s3`
- [x] Embedding providers: `embeddings.hash` (offline default) + `ollama` + `openai`
- [x] Vector providers: `vector.in_memory` + `vector.pgvector`
- [x] Settings resolution: env layer (`HRAGENTS_PROVIDER_*`, `.env` loaded) with fail-fast validation
- [x] `health_check` declared on every provider + masked-secret contract (`mask_secrets`)
- [x] **Complete matrix: 20 providers across 9 capabilities** — every capability has a zero-config default
- [ ] Provider settings audit entries (field names only, values redacted) — Phase 5
- [ ] Live adapter implementations for email/whatsapp/calendar/storage (configs + builders now; runtime in Phase 7)

---

## Phase 5 — Multi-department architecture

- [x] Workspace definitions (department packs registry) — `src/hr_agents/workspaces.py`: 9 packs with
      agent/tool/knowledge scopes, read/write permissions, routing keywords, deterministic fingerprint
- [x] Front door router: deterministic dispatch when workspace explicit; LLM intent classification only for ambiguous messages; **never executes consequential actions** — keyword router + explicit hint (`services/front_door.py`); Ask HR answers via `PolicyAssistant` and ungrounded answers deterministically escalate (`services/chat.py`, `POST /v1/chat`, SSE `/v1/chat/stream`); ambiguous messages fall back to Ask HR (an LLM intent classifier remains a later refinement); multi-department messages surface ranked `alternates` as `handoff_options`
- [x] RBAC: roles (hr_admin, recruiter, finance, manager, employee) × permissions — `src/hr_agents/rbac.py`,
      router-level enforcement, stricter checks on overrides, payroll sign-off/export, and compliance execution;
      role-bound API keys via `HRAGENTS_API_PRINCIPALS`
- [x] Tenant model: `tenant_id` on all tables + Postgres RLS policies — migration `0006_tenancy` (31 tables,
      `ENABLE`+`FORCE` RLS, `tenant_isolation` policies with `USING`/`WITH CHECK`, fail-closed to the default
      tenant when unset), `db/rls.py` single source of the policy SQL, `sync_session_scope(tenant_id=…)` sets
      the transaction-local GUC, RLS read/write fencing covered by `tests/db/test_rls.py` on Postgres
      (ADR 0006)
- [x] Workspace context isolation (knowledge, tools, conversations) — chat scopes agent
      knowledge namespaces per routed workspace; tool access is intersected with the pack's
      declared scope via `ToolRegistry.scoped()` (`AgentDeps.for_workspace`), out-of-scope calls
      are denied and audited, and a conversation is pinned to its workspace (cross-workspace
      continuation returns 409); `tests/tools/test_catalog.py` pins packs to the canonical
      `TOOL_NAMES` catalog and to real agent names
- [~] Chat conversation persistence — in-memory `ConversationStore` behind persistence primitives; Postgres adapter lands with the Phase 6 UI work
- [x] Cross-workspace request handoff ("handle onboarding for Budi") — `RouteDecision.alternates`
      ranked deterministically (EN/ID), `ChatReply.handoff_options`, and `HandoffService`
      (`services/workspace_requests.py`) queues a human-invoked `WorkspaceRequest` in the target
      workspace (audited as `handoff.requested`, never agent-invoked); `POST/GET /v1/chat/handoffs`;
      in-memory store behind primitives, Postgres adapter with Phase 6
- [x] Employee data model (HRIS-lite core: employees, contracts, documents, org units) — Phase 8.0/8.4
- [x] Retention & erasure engine (UU PDP: per-entity retention policies, delete/anonymize jobs) — Phase 8.9

## Phase 6 — Web app + PWA (`web/`)

### 6.0 Stack & project setup
- [x] Vite + React 19 + TypeScript project in `web/` (Node 26 + npm, `web/.nvmrc`, lockfile committed)
- [x] Tailwind CSS + shadcn/ui component library (Tailwind v4 CSS-first tokens, `cn` merge package)
- [x] TanStack Query (server state) + Zustand (workspace/UI state)
- [x] API client generated from the live OpenAPI schema (`scripts/export_openapi.py` →
      `docs/api/openapi.json` → `openapi-typescript`/`openapi-fetch`; `docs/api/openapi.yaml` legacy)
- [x] ESLint + Prettier + `tsc --noEmit` gate in CI (`web` job, drift-checked generated types)
- [x] Static build served by FastAPI (`/app`) in self-host image; SPA fallback routing (`_mount_web_app`)

### 6.0.1 Design system (locked — see `docs/plan/product-concept.md` §7)
- [x] Design tokens: neutral ramp (cool gray), accent `#2563EB`, status amber/red/green — single source
      `web/src/styles/theme.css`; a guard test bans hex literals anywhere else in the web source
- [x] Dark mode via token swap (full ramp recorded in §7.1)
- [x] Typography: Inter (UI) + JetBrains Mono (scores/IDs); scale 12–30, weights 400/500/600 (self-hosted)
- [~] Component kit: shadcn/ui themed to tokens (button, input, table, dialog, tabs, badge, progress,
      command, sonner, …) + `StatusBadge` (icon+label mandatory), `ScoreBar`, `EmptyState`
- [ ] Attention-first home: "Needs you today" + "Watching" sections wired to real queues (layout + empty states now)
- [~] Three-rooms workspace layout component (Board / Queue / Chat) — structure + placeholders;
      a workspace data endpoint lands with the chat UI slice
- [~] Accessibility pass: focus rings, reduced motion, icon+label status primitives in place;
      full WCAG AA audit later
- [ ] Mobile-first check at 390px viewport (queues, approvals, chat)

### 6.1 Shell & auth
- [~] App shell: sidebar workspaces, topbar, responsive layout (icon rail on mobile; bottom bar later)
- [ ] Auth screens: login, session handling, password reset
- [ ] Mobile-first layouts (solo HR lives on their phone)
- [x] i18n from day one: English + Bahasa Indonesia (locale files, language switcher, key-parity test)
- [ ] Settings → Connections: provider list with health badges, config forms (schema-generated), Test buttons, env-lock padlocks

### 6.2 Chat front door
- [x] Chat UI with workspace quick-switch (sidebar rail; every workspace's Chat room, Ask HR runs
      the front door with routing and handoff suggestions)
- [~] SSE streaming from FastAPI — the client uses `POST /v1/chat` (status codes drive the
      409 conversation-split); upgrade to event streaming once the backend emits progressive events
- [ ] Tool-call visibility (which agent is acting, what it read)
- [~] Workspace-scoped conversation history — client threads are per-workspace and server-pinned
      (409 on cross-workspace continuation, visible restart); Postgres store with the UI phase

### 6.3 Recruitment workspace
- [ ] Pipeline board (kanban: received → screened → interview → offer) with dnd-kit
- [ ] Candidate detail: score breakdown, evidence refs, timeline, flags
- [ ] Review queue for HITL (soft-rejection sign-off, anomalies, calendar)
- [ ] Scheduling view (slots, confirmations, reschedules)
- [ ] Batch import UI (XLSX/CSV + drag-drop CVs) with progress

### 6.4 Other workspaces (Wave-1 surfaces)
- [ ] Policy workspace: Q&A with citations + knowledge browser
- [ ] Onboarding workspace: checklists, document collection status
- [ ] Records workspace: employee directory, expiry alerts
- [ ] Payroll workspace (prep & verify): data assembly, anomaly flags, export
- [ ] Audit viewer: searchable, verified chain, export
- [ ] Skills/knowledge editor (markdown editing with preview, versioning)

### 6.5 PWA
- [ ] `vite-plugin-pwa`: manifest, service worker, offline shell
- [ ] Install prompt + push notifications (interview confirms, approvals, SLAs)
- [ ] Lighthouse PWA + mobile performance pass

## Phase 7 — Integrations (all via the provider layer, `docs/architecture/providers.md`)

> Detailed remaining checklist from this phase to release: `docs/plan/remaining-work.md`.

### 7.1 Messaging
- [ ] `email_send` providers: SMTP (default) + Resend
- [ ] `email_receive` providers: IMAP poll (default, no public URL) + Resend webhook
- [ ] `whatsapp` providers: Meta Cloud API + manual `wa.me` links fallback (default until connected)
- [ ] Telegram bridge (optional provider)
- [ ] Webhook signature verification + replay protection
- [ ] Response SLA timers (anti-ghosting guarantees)
- [ ] Deployed behind Cloudflare Tunnel instructions for self-host webhooks

### 7.2 Google Workspace / Microsoft 365
- [ ] Gmail send + thread sync
- [ ] Google Calendar: free/busy, slot proposal, invites, reschedules
- [ ] Google Drive: document import (CVs, policies)
- [ ] Google Sheets: candidate/employee import-export
- [ ] Microsoft Graph (Outlook/Calendar/OneDrive) — same adapter interface

### 7.3 Files & office reality
- [ ] XLSX/CSV import with column-mapping UI
- [ ] Export: XLSX reports, PDF feedback letters
- [ ] Office Connector: local folder sync agent for NAS/shared drives (only if demand)

### 7.4 MCP layer
- [ ] MCP client manager: configs, health checks, namespaced tools, graceful degradation
- [ ] MCP servers catalog (disabled by default): ATS (Greenhouse/Lever), HRIS (Talenta/Gadjah), Slack, calendars
- [ ] Approval hook for destructive MCP tools (e.g., ATS status change)
- [ ] Expose `hragents-mcp` server (queue, evaluations, candidate status) for external tools

## Phase 8 — Departments (each = skills + tools + agents + UI + tests + knowledge)

### 8.0 Shared engines (foundation for every department) `DONE`
- [x] **Employee core**: `Employee` lifecycle (onboarding → probation → active → notice → offboarded) with guarded transitions; org units; document vault with expiry tracking
- [x] **Contract core**: PKWT/PKWTT structural rules, probation restrictions, expiry/probation math, completion-compensation flag (structure only), termination records
- [x] **Approval engine**: generic HITL queue — create → assign by role → decide → SLA escalate → expire; agents can request, never decide; every transition audited
- [x] **Task engine**: create/assign/complete/cancel, overdue detection, agent-created tasks labeled; queue sorted overdue-first
- [x] **Rate table engine**: operator-owned statutory rates; structure without numbers; verification gate (`usable`); payroll can never silently use unverified values
- [x] Persistence: 7 tables + Alembic `0002_people` (16 tables total)
- [x] API surface: employees, contracts, approvals, tasks, rate tables (18 endpoints) — all audited, integration-tested
- [x] Tests: 111 new (engines + API integration) — suites pass offline, no LLM involved

### 8.1 Recruitment (deep build — completes Phase 4)
- [ ] (see Phase 4.1–4.6) + offer management + rejection communication flows

### 8.2 Policy & Knowledge
- [x] `PolicyAssistant` agent with citation-mandatory answers (Phase 4.4)
- [ ] Knowledge base: company policies + Indonesian labor law (verified sources)
- [ ] Policy change workflow (edit → version → effective date)

### 8.3 Onboarding `DONE` (Wave 1 scope: checklist + documents + contract prep)
- [x] Template-driven checklist engine: steps (document/task/contract/account/orientation/confirmation), role+contract-type matching, deterministic template content hash for audit reconstruction
- [x] Plan instantiation: per-employee plan created from a template; underlying tasks auto-created via the Task engine
- [x] Progress + blockers: required-step progress, overdue steps, plan completion timestamp
- [x] Human completion enforced: agents cannot complete checklist steps; waiving requires a human + reason (audited)
- [x] Document collection: steps link to the employee document vault; kind mismatch rejected; `auto_complete_document_step` is the one agent-allowed completion tier — requires a VERIFIED document and no human sign-off
- [x] Starter template shipped (`default_engineering_template`) for engine bootstrap; operators create their own in the API/UI
- [x] API surface: 8 endpoints (templates CRUD-lite, plans, step complete/waive/link-document, document status)
- [x] Tests: 34 new (service + API integration); audit chain covers every transition
- [ ] Contract preparation templates (PKWT/PKWTT document generation) — later
- [ ] Accounts/equipment inventory tracking — later
- [ ] Onboarding workspace UI (Phase 6)

### 8.4 Records (HRIS-lite)
- [x] Employee CRUD (API), documents vault (API), contract lifecycle (API)
- [x] Expiry alerts (documents + contracts; task generation)
- [ ] Natural-language lookup ("who's on probation?") — agent tool
- [ ] Org chart + reporting lines (data + API exist; UI later)

### 8.5 Time & Leave `DONE` (Wave 1 scope: policies, balances, requests, calendar)
- [x] Leave types (annual/sick/personal/maternity/paternity/bereavement/marriage/unpaid) with operator-configurable policies — **no hardcoded statutory numbers**
- [x] Accrual methods: flat-monthly, lump-sum annual, per-event cap, none; min-service gating; carryover with caps
- [x] Working-day math: weekend exclusion + public holiday calendar (operator-set)
- [x] Balances: entitled / used / pending / carried-over / adjustments; manual adjustments audited with reason
- [x] Requests: validation chain (documents, caps, min service, balance, overlaps) → routed through the Approval engine → synced on decision; `requires_approval=false` policies auto-approve in the auto tier
- [x] Calendar view (who is on leave), pending queues, per-employee history
- [x] API: 12 endpoints (policies, holiday calendar, balances, adjust, requests, cancel, sync, calendar)
- [x] Tests: 36 new (service + API integration), audit chain covers every transition
- [ ] `LeaveAssistant` agent (policy Q&A, request drafting over chat) — agent phase
- [ ] Leave workspace UI (Phase 6)

### 8.6 Payroll (prepare & verify ONLY — never executes payments) `DONE` (Wave 1 core)
- [x] Run lifecycle: draft → assembling → ready_for_review → pending_signoff → approved → exported (or rejected/cancelled); run kinds (monthly, THR, adjustment, final)
- [x] Computation consumes **verified rate tables only** — missing/unverified required tables raise blocking ERROR anomalies instead of guessing
- [x] Overtime (first-hour × subsequent multipliers from the overtime table), BPJS employee+employer shares with wage caps, PPh 21 from a TER-style bracket table (skipped with a warning when unverified)
- [x] Anomaly detection: negative net (ERROR, blocks sign-off), excessive overtime (WARNING), net deviation vs previous run (WARNING), missing rate tables (ERROR)
- [x] **Human sign-off via the approval engine (Finance role)** — agents cannot decide; run export blocked until approved
- [x] XLSX review packet (per-employee lines, totals, run info, explicit "no payments executed" notice); GET packet endpoint with notice header
- [x] API: 10 endpoints (runs, inputs, compute, submit, decision sync, export, packet.xlsx, cancel)
- [x] Tests: 23 new (service computations with exact expected values + API integration flows); audit chain covers every transition
- [ ] Attendance/overtime import (CSV/XLSX) from office machines — Phase 7 files work
- [ ] Payslip distribution coordination (human-approved) — Phase 7 messaging
- [ ] Payroll workspace UI (Phase 6)

### 8.7 Performance `DONE` (Wave 1 scope: cycles, forms, summaries, light goals)
- [x] Review cycles: operator-set rating scale (no hardcoded 1–5), deterministic lifecycle (draft → active → reviewing → completed/cancelled), assignment required before activation, close blocked on pending forms + unfinalized summaries
- [x] Form collection: per-reviewer assignments with due dates, human-only submissions validated against the cycle scale, skip-with-reason for departed reviewers, reviewer workload query
- [x] Summary drafts (human-edited): agent drafts grounded in submitted ratings (`draft_summary` requires ≥1 submitted form), **human-only finalization**, finalized text terminal (no re-draft)
- [x] Reminder runner: creates system tasks for due forms + unfinalized summaries, deduplicated per assignment/summary so it can run daily
- [x] OKR/goal tracking light: title/metric/cycle link, append-only progress updates, human activate/complete/cancel (cancel needs a reason), overdue detection
- [x] API: 17 endpoints (cycles CRUD-lite + transitions, assignments submit/skip/list, summaries draft/finalize, goals lifecycle, reminders run)
- [x] Persistence: 4 tables (`review_cycles`, `review_assignments`, `review_summaries`, `goals`) in migration `0004_growth_offboarding`
- [x] Tests: 29 service + 9 API integration
- [ ] `ReviewAssistant` agent (summary drafting, tone-adjusted) — agent phase
- [ ] Performance workspace UI (Phase 6)

### 8.8 Offboarding `DONE` (Wave 1 scope: checklists, assets, final pay coordination)
- [x] Templates: reason/role matching, operator-editable steps (task/document/asset/account/interview/handover/final-pay/confirmation), deterministic template content hash for audit reconstruction
- [x] Plan instantiation: per-employee exit checklist, tasks auto-created via the Task engine, employee moved to `notice_period` on plan start
- [x] Human completion enforced: agents cannot complete/waive steps (waive requires human + reason); plan completion is an explicit human action
- [x] Exit interview scheduling + knowledge handover notes attached to the plan
- [x] Asset tracking: assigned → returned / missing → written-off (human + reason); assigned/missing assets block clearance
- [x] Final pay coordination: opens a FINAL payroll run + Finance task; run still requires inputs, verified tables, anomaly clearance, and Finance sign-off — **no payments executed**
- [x] Completion: all required steps + zero asset blockers, then `finalize_employee_exit` transitions the employee record (keeps its own guards)
- [x] API: 19 endpoints (templates CRUD-lite + default, plans + steps/waive/interview/handover/final-pay/complete/finalize, assets + return/missing/write-off/clearance)
- [x] Persistence: 3 tables (`offboarding_templates`, `offboarding_plans`, `offboarding_assets`) in migration `0004_growth_offboarding` (28 tables total)
- [x] Tests: 21 service + 9 API integration (+6 shared DB round-trip tests covering all new tables)
- [ ] Asset inventory at onboarding time (assign equipment on day one) — later
- [ ] `OffboardingCoordinator` agent (checklist chasing, exit interview summaries) — agent phase
- [ ] Offboarding workspace UI (Phase 6)

### 8.9 Compliance (cross-cutting) `DONE` (Wave 1 core: consent, retention, erasure, breach, audit verify)
- [x] Approval/task audit trails for every HR operation
- [x] Consent registry: purpose-scoped grants/refusals/revocations with expiry, lawful basis, capture evidence, and `active` checks (`has_active_consent`); agents may record evidence, only humans revoke
- [x] Retention engine: per-entity operator policies (months + delete/anonymize action, **no hardcoded statutory window**), record ledger with anchor dates + overrides, deterministic scan (due / held / uncovered), dry-run and scheduled purge (`by="system"`), per-record purge handlers for store mutation, full audit trail
- [x] Legal holds: human-only, reason required, never auto-purged by retention or erasure; reported per record
- [x] Erasure workflow (UU PDP / GDPR shape): request → human identity verification → Data Protection approval (shared engine; agents can request, never decide) → **separate** human execution; per-record dispositions (deleted / anonymized / retained under hold) and consent revocation
- [x] Breach workflow: operator-editable checklist templates (starter default, not legal advice), materialized steps with configurable offsets, notification log, forward-only status lifecycle (close requires all required steps + closure note), overdue-step reporting
- [x] Audit-chain verifier: end-to-end hash chain check with first-invalid-sequence reporting (`GET /v1/compliance/audit/verify`)
- [x] API: 27 endpoints (consents, retention policies/records/scan/purge/holds, erasures + decision sync/execute, breaches + template/steps/notifications/status/overdue, audit verify)
- [x] Persistence: 5 tables (`consent_records`, `retention_policies`, `retention_records`, `erasure_requests`, `breach_incidents`) + Alembic `0003_compliance` (21 tables total)
- [x] Tests: 48 new (service + API integration); agent/human actor boundaries, legal-hold precedence, and dry-run no-mutation covered explicitly
- [ ] Labor-law knowledge base with citations — Phase 8.2 (knowledge docs exist in `skills/`)
- [ ] WLKP/BPJS reporting reminders — Phase 8.2/8.6 follow-up
- [ ] Scheduled job wiring (retention sweep, breach overdue alerts) — Phase 7/9 ops
- [ ] Pipeline consent checkpoint (halt candidate processing when `has_active_consent` is false) — Phase 8.1 integration
- [ ] Compliance workspace UI (Phase 6)

## Phase 9 — Deployment & operations

- [x] `LICENSE` file (Apache-2.0)
- [x] Freelance services one-pager — README "Work with the author" section live (full landing page later, Phase 10)
- [ ] Setup wizard + one-command self-host install (this *is* the adoption strategy)
- [ ] Self-host distribution: one-command compose, setup wizard, backup/restore docs
- [ ] Local-model mode (Ollama) — fully offline operation
- [-] Managed cloud SaaS + billing (deferred until proven demand)
- [ ] Dedicated-instance option (BYOC: their cloud account) — only if requested
- [ ] Region options: Jakarta/Singapore deployment recipes
- [ ] Security hardening: key management, secrets rotation, rate limits, pen-test checklist
- [ ] Observability: OTel traces, Prometheus metrics, Grafana dashboards, cost tracking
- [ ] Data governance: export, deletion procedures, DPA template

## Phase 10 — Paper, docs & publication

- [ ] Paper: recruitment deep-dive + the "HR department of one" platform framing
- [ ] Measured results: load tests, eval scores, fairness-audit results, latency budgets
- [ ] `landing/`: Next.js public site (SEO pages: HR automation Indonesia, open-source ATS alternative)
- [ ] `landing/`: docs section, changelog, demo video embed
- [ ] `landing/`: "Work with me" page — freelance integration/consulting offer with contact
- [ ] README: demo dataset, screenshots, 5-minute quickstart
- [ ] README "Work with the author / freelance integration" section: name, product, contact, services offered
- [ ] Demo video / GIF walkthrough
- [ ] API docs site + operator runbooks
- [x] `CONTRIBUTING.md` + `CODE_OF_CONDUCT.md` (landed early — see Phase 1)
- [ ] Public release on GitHub (Apache-2.0), tagged version, release notes

---

## Appendix A — Explicitly not in scope (revisit only on real demand)

- [-] Payment execution / bank file generation (payroll output is for review only)
- [-] Biometric/fingerprint attendance hardware drivers (CSV import covers it)
- [-] Native mobile apps (PWA instead)
- [-] Full accounting/ERP features
- [-] Self-hosted email server (SMTP to their existing provider)
- [-] Rust/Go core rewrite — rejected: bottleneck is LLM inference/network, not CPU language performance
- [-] Rust/Go AST microservice — deferred; extract only if profiling proves saturation at scale
- [-] Next.js for the dashboard — rejected: auth-walled SPA gains nothing from SSR and adds a Node runtime to every self-host deployment

## Appendix B — Hard prohibitions (never ship)

- No shell/`run_command` tool exposed to any agent
- No training or fine-tuning on historical hiring outcomes
- No protected attributes in scoring inputs (enforced by schema + fairness harness)
- No auto-rejection when any anomaly flag is present
- No anonymous HITL overrides
- No hidden ranking — every score inspectable with evidence
