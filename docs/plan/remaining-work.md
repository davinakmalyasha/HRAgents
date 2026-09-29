# Remaining Work — core integrity, then MCP layer to paper & release

Status snapshot: **2026-09-29**. Everything up to and including Phase 5 (multi-department
architecture: workspaces, RBAC, front door + Ask HR chat, tenancy + RLS, workspace-scoped tools,
cross-workspace handoff) is built and tested. Stage 0 of the core work landed: **the evaluation
worker now runs**, all five agents are constructed in production, the rate-table API makes payroll
reachable, erasure stops lying, and `/readyz` + `/metrics` make a stopped pipeline visible.
**1105 tests (1101 passed, 4 skipped for Postgres) · 92% coverage · ruff + mypy clean**.

> **What changed, and why it mattered.** The API accepted an application and returned `202`, but
> nothing ever claimed the queue — the core loop was inert and looked like success. The container
> image shipped without `skills/`, so every agent ran with no runbooks. Payroll could not be
> completed through the API at all (no way to add rate-table entries). Erasure reported
> `{"action":"deleted"}` and deleted zero bytes, in both the API response and the audit chain.
> Those are fixed and regression-tested. The next slice is the **trust boundary** (the named-human
> gate is still a substring test on a self-declared string) and **scoring generalization** (a
> qualified accountant is auto-rejected today). The measured defect list is
> `docs/plan/master-build-plan.md` Appendix C.

This file is the detailed checklist for everything **not yet done**, in build order. The master
plan (`master-build-plan.md`) keeps the high-level status; this file is the working document for
the phases that remain.

Legend: `[ ]` not started · `[~]` partially done · `[x]` done.

---

## 0. Core integrity (the highest-leverage remaining work)

> **Why this is first.** The central claim is "a named human gates every consequential outcome,
> and every decision is reconstructible." Today the gate is `if not by.startswith("agent:")` on
> a string the client typed, and the principal FastAPI already authenticated is discarded by every
> router. Everything else is subordinate to fixing that.

- [ ] **One actor identity from the trust boundary.** Resolve `Principal` once per request onto
      `request.state.principal`; every service takes `actor: ActorRef` instead of `by: str`. Keep
      the body name only where a *different* human is genuinely being named (an override reviewer)
      and require a reason when it differs from the principal. ~100 schema fields plus the web
      app — one router at a time, with the web change in the same commit.
- [ ] **One `classify_actor()` and one `require_named_human()`**; delete the 11 + 8 reimplementations.
      Fixes `agent:x` recorded as `ActorType.HUMAN` in `employees.py`, `contracts.py`, and
      `rate_tables.py`, plus the three `_require_human` variants that accept `""`.
- [ ] **Gate the ten ungated consequential operations**: `EmployeeService.transition`,
      `mark_document_verified` (the check lives in the router, not the service),
      `contracts.activate`/`terminate`, `tasks.complete`/`cancel`,
      `leave.set_policy`/`adjust_balance`, `payroll.mark_exported`/`cancel_run`, and
      `offboarding.finalize_employee_exit` (which validates nothing when the plan is complete).
- [ ] **Bind approval decisions to `assignee_role`** — `decide` checks only that the actor is not
      `agent:`, so a `MANAGER` can decide a `FINANCE`-assigned payroll sign-off.
- [ ] **Fix the 68 write endpoints guarded by a READ permission** and wire the 6 dead permissions
      (`PEOPLE_WRITE`, `PAYROLL_WRITE`, `COMPLIANCE_WRITE`, `RATES_VERIFY`, `AUDIT_READ`,
      `ADMIN_MANAGE`).
- [ ] **Type errors once**: typed domain exceptions + a central status map instead of
      `if message.startswith("unknown")` in 7 routers; then the missing
      `RequestValidationError` → `problem+json` handler and stable `type` URIs, so the frontend
      stops matching English prose to pick an error message.
- [ ] **`Decimal` money with `ROUND_HALF_UP`**; move the 173-hour divisor and 1.5×/2.0× overtime
      multipliers into verified rate tables; progressive PPh 21 TER brackets; honour
      `absence_days`; add a totals-equal-lines invariant.
- [ ] **Business dates in WIB**: `HRAGENTS_TIMEZONE` (default `Asia/Jakarta`) through the ~20 bare
      `date.today()` calls. On a UTC host every business date is wrong for 17 hours a day.
- [ ] **A unit of work with optimistic concurrency**: one transaction per service method, a
      `version` column, and a lost-update guard on the ~35 read-modify-write sites. Also what
      makes a mid-loop erasure failure detectable instead of silent.
- [ ] **Schema integrity**: `CHECK` constraints on the enum-like and numeric columns, foreign keys
      on the 8 orphan tables, and `ORDER BY` in the DB adapters instead of 12 Python re-sorts.
- [ ] **Real purge handlers for candidate, application, employee, document, and payroll records**,
      and feed the retention ledger from the services that create records (today it is
      operator-manual, so `execute_purge` finds nothing to do).
- [ ] **Consolidate the 13 `_record` audit methods, 6 state-transition formats, and the triplicated
      approval→status sync** behind one auditor, one declarative state machine, and one
      `ApprovalEngine.await_decision()`.

---

## 0.1 Known leftovers before the MCP layer (small, tracked here for completeness)

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
      (`scripts/run_scheduler.py`, `audit-verify` job) runs the verification on a schedule;
      compose cron wiring lands in Phase 9.
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

## 0.2 Scoring generalization to non-engineering roles

> **The single most commercially damaging defect, and it is silent.** The four
> dimensions are a backend-engineer rubric promoted to a universal schema. Worked
> example with the code as written: an 8-year accountant with an ACCA membership
> applying for a Finance Supervisor role scores `S_tech ≈ 0.58` → `REJECT_AUTO`
> with no human in the loop and no sign-off required. `systems_literacy` matches
> only `{database, devops, cloud, systems, data}` and 15 engineering keywords;
> `publications` is 0.0 for every non-research role; the seniority tiers are
> engineering words, so "Accounting Supervisor" matches none.
>
> The name-swap fairness harness **cannot** catch this: swapping a candidate's
> name does not change the shape of the score distribution. It proves the
> arithmetic is invariant; the risk is in the *extraction* and the *rubric*.

- [ ] **`DimensionTemplate` as data, not code**: `{job_family, dimensions: [{key, weight, scorer,
      evidence_requirement}], thresholds}` — versioned, audited, and snapshotted into every
      evaluation. The scorer stays deterministic; only the dimension list becomes data.
- [ ] **Composable primitive scorers with per-family taxonomies**: `evidence_count`,
      `evidence_density(taxonomy)`, `tenure_saturation(cap)`, `credential_registry(family)`,
      `title_seniority_tiers(family)`. A single per-family keyword taxonomy is the change that makes
      the model general.
- [ ] **Evidence-first scoring**: a dimension contributes nothing without at least one `EvidenceRef`
      above a confidence floor. Structurally kills a whole class of extraction-failure silent passes.
- [ ] **Real credential registries per family** (BNSP, AWS/Google/Azure, ACCA/CPA/CFA). Today
      `verify_credential` is a dict lookup with no data, so a genuine certificate and a Coursera
      badge score the same.
- [ ] **Templates for `engineering`, `finance`, `sales`, `admin`, `operations`,
      `customer_support`**, with thresholds as template data behind the same `verified` gate as rate
      tables. **The engineering template must produce byte-identical scores to today** — that is the
      regression test proving the generalization is additive.
- [ ] **Replace the `σ ≤ 0.05` gate.** Today `scoring_runs` defaulted to 1, so `sigma` was always
      `0.0000` and the gate always passed — a *degraded* path (one extraction) was more trusted than
      a careful k=3 one. Replace with an evidence-sufficiency gate (every dimension evidenced, zero
      flags, minimum run agreement) and surface per-dimension run agreement in the UI, which is both
      honest and a better product surface than a bare σ.
- [ ] **Extraction fairness pairs on the agent, not the scorer**: generated CV pairs differing only in
      name, gender-coded name, photo, or school, run through the *agent*, asserting identical
      extracted skills and scores. `tests/services/test_fairness.py` currently swaps fields the
      scorer never reads, so it proves nothing about the real risk.

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
- [x] Classify tools as `read` / `write` / `destructive` in the registry (`ToolDefinition.impact`)
- [x] `destructive` ⇒ execution blocked; creates an approval through the shared Approval engine
      (`ApproverRole.MANAGER`/`HR_ADMIN` as configured) carrying a dry-run preview
- [x] On approval: execute once, record the approval id in the audit payload; on rejection/expiry:
      no side effect, agent informed
- [x] Tests: destructive tool cannot execute without a named human decision (negative tests first)
- [ ] Remaining: register the catalog's external tools with explicit impacts, and surface the gate
      through an agent-facing API so an agent can request approval in-line

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
- [x] Pipeline board (five stages: intake → screened → needs decision → interview → closed) with
      job filter and ranked cards; dnd-kit drag (pointer + keyboard) routed through
      `intentForDrop` and validated server-side against the designed transition table
      (named human + reason; sign-off/scheduling never bypassed)
- [x] Candidate detail: status + timeline, score/sigma/priority, evaluation breakdown with
      rationales, flags, and policy decision; the weighted-contribution formula opens inline
      and every dimension expands to its evidence refs (locator, excerpt, source, confidence)
- [x] Review queue for HITL: gated applications with evaluation context, named-reviewer
      sign-off with reason codes, audit receipt shown; uses the override endpoint with reason codes
- [x] Scheduling view: proposals list with slots (candidate timezone), auto vs. needs-approval
      vs. no-mutual-slots reconciliation, policy decision + reasons, candidate deep link
- [x] Proposal decision endpoint: confirm/cancel/reschedule with a named human; the linked
      `scheduling` approval is decided through the shared engine (pending confirmations surface
      in the attention queues); invite dispatch lands with the Phase 7 messaging bridge
- [x] Batch import UI (CSV paste/drop + drag-drop CVs, consent confirmation, per-item
      conflict report); XLSX parsing deferred — CSV covers the need today
- [~] Candidate communication panel (application detail): gated rejection/offer queueing with
      named-human approvers, full body review before dispatch, `mark sent` evidence, history,
      the transport state the backend records (recipient, provider, attempts, last error), the
      inbound replies the mailbox poll captured, and a wa.me link composer for WhatsApp messages
      (the human opens it, sends, then records dispatch). A pre-queue preview
      endpoint now renders the exact rejection message and lists the gates that
      block it, and the panel makes that a two-step (preview, then queue). Still
      open: the Meta Cloud WhatsApp transport
- [x] Job management: create/edit dialog, status lifecycle with a named actor, dimension-weight
      editor with inline sum-to-1.0 validation (`/w/hiring/jobs`)
- [x] Offer records (application detail): terms with append-only revisions, submit → shared
      approval queue, approve/withdraw, offer message through the outbox, acceptance/decline
      recording; offer expiry runs on the scheduler (`offer-expiry` job)

### 2.5 Department workspaces (Wave-1 surfaces)
- [~] Ask HR: chat with citations and handoff suggestions done; progressive SSE streaming and
      tool-call visibility remain (see polish backlog)
- [x] Onboarding workspace: plan board (progress, blockers, overdue first), checklist room ordered by
      what needs a human now, complete/waive with a named actor (a waiver needs a reason and is not
      offered for required steps), document collection status with linking of an on-file document,
      and starting a plan for an existing hire or a new one created in the same flow
- [x] Records workspace: employee directory filterable by org unit, org chart with roll-up
      headcount, document vault ordered by urgency, expiry alerts, and named-human document
      verification (backend: `/v1/documents`, `/v1/documents/{id}/verify`, `/v1/org-units`)
- [ ] Leave workspace: policies, balances, request calendar, approval queue
- [ ] Payroll workspace: run assembly, anomaly review, sign-off submission, XLSX packet download
      (with the "no payments executed" notice rendered in the UI)
- [ ] Growth workspace: cycles, form collection, draft → finalize editor, goals
- [ ] Offboarding workspace: exit checklists, asset clearance, handover notes, final-pay link
- [ ] Compliance workspace: consent registry, retention scan/purge, erasure workflow, breach
      checklist, audit-chain verifier with visible integrity result
- [ ] Audit viewer: searchable entries, chain verification badge, export

### 2.6 PWA
- [x] `vite-plugin-pwa`: manifest, service worker, offline shell (static assets only —
      no API caching, so an offline queue can never serve stale decisions)
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
- [x] One-command self-host: `Dockerfile` (multi-stage, non-root, dashboard baked in) and a
      compose stack with postgres+pgvector, redis, minio, mailpit, a one-shot `migrate` service
      the API waits on, and `scheduler`/`messaging` loops; `/healthz` + `/readyz` (per-dependency
      readiness, 503 when degraded)
- [ ] Provider settings UI with health badges, env-lock indicators, masked secrets (Settings →
      Connections)
- [ ] Local-model mode (Ollama): fully offline operation, documented model floor (size/quality)
- [x] Backup/restore script with a verification drill (`scripts/backup.py --verify` restores into a
      scratch database and re-verifies the audit chain) and a runbook in `docs/deployment.md`;
      measured RTO/RPO numbers are still to be recorded
- [ ] Region recipes: Jakarta / Singapore deployment notes; Cloudflare Tunnel guide for webhooks
- [ ] Security hardening: key management, secrets rotation, rate limits, upload scanning hook,
      pen-test checklist, dependency scanning in CI
- [ ] Observability: OTel traces (API → pipeline → agents), Prometheus metrics, Grafana dashboard,
      LLM cost tracking (token accounting per model)
- [ ] Data governance: full export, deletion procedures, DPA template, subprocessor list
- [~] Scheduled jobs: retention sweep (dry-run default, `--purge` to apply), approval SLA
      escalation/expiry, breach overdue reporting, review reminders, contract + document expiry
      tasks, offer expiry, overdue-tasks report, audit-chain verification, and the reply-SLA
      anti-ghosting check (a dispatched message with no reply after 72h becomes a recruiter
      follow-up task) — all through `scripts/run_scheduler.py` (one CLI over the app containers,
      `--job` selectable, `--json` output, nonzero exit on job failure), and composed into
      `docker-compose.yml` as a 15-minute loop. Remains: alerting on the report.
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

The order changed on 2026-09-29. The previous list put MCP and the landing site
ahead of anything that made the product work, while the core loop was inert and
the scoring model silently auto-rejected non-engineers. The new order is
"make it true, then make it good, then make it known".

| Order | Workstream | Depends on | Why this order |
|---|---|---|---|
| 1 | **Core integrity** (§0): the trust boundary, the shared primitives, `Decimal` money, WIB dates | — | The project's promise is an auditable record of human decisions. Today the actor is a self-declared string. Nothing else raises the floor |
| 2 | **Scoring generalization** — `DimensionTemplate` registry keyed by job family | 1 | The system auto-rejects accountants, sales, and admin hires. That is a correctness failure with real people on the other end, and the fairness harness structurally cannot catch it |
| 3 | **Dashboard** (§2): approvals inbox, home fix, auth, XLSX, mobile pass, streaming | 1 (typed error codes) | Makes the product usable by a human on a phone. The approvals inbox is one screen that makes five workspaces actionable |
| 4 | **Knowledge + compliance calendar** — Indonesian statutory content, THR, the dated obligations nobody else ships | 1, 2 | The only genuinely differentiating feature for this market, and it needs no LLM |
| 5 | Evals expansion (§4) — generated 50-profile set + extraction fairness pairs | 2 | Runs offline; feeds the paper and calibrates the templates |
| 6 | Ops hardening (§5) — wizard, demo dataset, alerting | 1, 3 | Must be stable before any public release |
| 7 | MCP layer, landing site, paper | 3, 4, 5 | Release last; the paper cites measured results |

**Cut for now:** the MCP layer is the lowest-value work on the list for a solo-HR
person who will never connect an ATS, and the landing site precedes having a
working install. Both stay in this file; neither should block the four above.

### Risk notes

- **The trust-boundary flip is the one change that can quietly break the product.**
  If the dashboard's `by` payloads stop matching the principal, sign-offs fail at
  runtime rather than at build. Mitigate by shipping the web change in the same
  commit as each router, and by writing the negative tests first.
- **The audit chain is the one thing that must not break mid-rewrite** — the
  project promises tamper-evidence. Migrate services *to* the shared auditor; never
  rewrite the hash semantics. The streaming-verify tests in `tests/services/test_audit.py`
  are the guard.
- **A literal big-bang rewrite of 26k LOC with one author is the highest-risk way
  to lose what works.** Build each shared primitive as an unused, tested module,
  prove the pattern on `compliance` (the best-tested service at 92%), then migrate
  the rest with the 1101-test suite as the net.
- **LLM latency** (mean ~82 s live) shapes the UI: progress states and "watching" sections
  are required before launch; do not hide processing time. Parallelising the k
  extraction runs (done) cuts it roughly k-fold.
- **Coverage floor**: keep ≥ 90% on `src/hr_agents`; new UI work must not dilute the invariant
  suite (scoring, policy, fairness, audit chain, payroll gates stay at 100% branch).
- **No scope creep into payment execution, biometric hardware, or accounting** — see
  `master-build-plan.md` Appendix A.
