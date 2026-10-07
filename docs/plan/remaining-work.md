# Remaining Work — core integrity, then MCP layer to paper & release

Status snapshot: **2026-09-30**. Everything up to and including Phase 5 (multi-department
architecture: workspaces, RBAC, front door + Ask HR chat, tenancy + RLS, workspace-scoped tools,
cross-workspace handoff) is built and tested. Stage 0 of the core work landed: **the evaluation
worker now runs**, all five agents are constructed in production, the rate-table API makes payroll
reachable, and `/readyz` + `/metrics` make a stopped pipeline visible. Block A landed after that:
**one identity module** now owns actor classification and the named-human gate, the ten
ungated consequential operations are gated, and a single extraction can no longer satisfy the
`sigma` gate. Block B is complete: **authentication happens once per request**, `ActorRef` carries
the actor together with its provenance, and **no request body in the API names the actor at all**.
**1287 tests (1283 passed, 4 skipped for Postgres) · ≥90% coverage · ruff + mypy clean**.

> **What changed, and why it mattered.** The API accepted an application and returned `202`, but
> nothing ever claimed the queue — the core loop was inert and looked like success. The container
> image shipped without `skills/`, so every agent ran with no runbooks. Payroll could not be
> completed through the API at all (no way to add rate-table entries). Erasure reported
> `{"action":"deleted"}` and deleted zero bytes, in both the API response and the audit chain.
> Three services wrote `agent:` onto the tamper-evident chain as `ActorType.HUMAN`, and every
> named-human gate accepted `system`, so a caller could decide an approval as `system`. All fixed
> and regression-tested. Block B then closed the trust boundary from the outside in: the actor is
> resolved from the API key in middleware, before routing, and **no request body names it** — the
> dashboard's "type your name here" fields are all deleted rather than quietly ignored.
>
> What was left was not attribution but **authority**: who may decide, and who may change which
> records. B3 has now landed. All 58 mutating routes that were authorized by a *read* permission
> name a write or self-service one, and the fence is a structural test that asserts the exact set
> rather than a count. Closing it needed a principal-to-employee binding, because "your own leave"
> is not expressible without one, and ownership checks in the services — a permission alone would
> have let any employee file leave for anyone by naming their id.
>
> Two things remain before this is finished: the **authorization matrix for managers and finance**
> (they read the employee directory but do not administer it, which is a decision to revisit per
> deployment), and **scoring generalization** (a qualified accountant is auto-rejected today). The
> measured defect list is `docs/plan/master-build-plan.md` Appendix C.

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

- [x] **One `classify_actor()` and one `require_named_human()`** (`hr_agents/identity.py`); the 11 + 8
      private copies are gone. Fixes `agent:x` recorded as `ActorType.HUMAN` in `contracts`,
      `employees`, and `rate_tables`; the three `_require_human` variants that accepted `""`; and
      the fact that **every** gate accepted `system`/`system:` — so `by="system"` decided an approval
      under a check reading "requires a named human actor"
- [x] **Gate the ten ungated consequential operations**: `EmployeeService.transition`,
      `mark_document_verified` (the check moved out of the router, where any agent tool or service
      bypassed it), `contracts.activate`/`terminate`, `tasks.complete`/`cancel`,
      `leave.set_policy`/`adjust_balance`, `payroll.mark_exported`/`cancel_run`, and
      `offboarding.finalize_employee_exit` (which had no gate at all)
- [x] `runs: min_length=2` — sigma is 0.0 by definition over one run, so a single extraction
      satisfied `σ ≤ 0.05` with the least evidence
- [x] Rate-limiter bucket eviction, and `X-Forwarded-For` honoured only behind an explicit
      `HRAGENTS_TRUST_PROXY_HEADERS=true` (it was a complete bypass on the unauthenticated path)
- [x] **Authentication middleware** (`hr_agents/api/auth.py`): the key is resolved once per request
      instead of once per guard, `client_key()`'s per-principal branch is live (it was unreachable
      dead code, because a dependency runs after all middleware), and **401 vs 403 are now
      distinguishable** — refused credentials are 401, a valid key whose role lacks a permission
      is 403. `create_app(settings)` makes the app and its middleware share one `Settings`.
- [x] **`ActorRef`** carries the actor *and* its provenance (`authenticated` / `system_job` /
      `agent_tool` / `legacy_string`), and `AuditEntry` records that plus the role.
      `HRAGENTS_ACTOR_NAME` names the local operator instead of writing `local-dev` on the chain.
- [x] **The recruiting group takes its actor from the principal, not the body** — 11 actor fields
      removed from `JobCreate`/`JobUpdate`/`JobStatusChange`/`AvailabilitySet`/
      `SchedulingProposalRequest`/`ProposalDecisionRequest` and the five communication requests;
      `services/recruiting.py` takes `actor: ActorRef`; the dashboard's three "type your name"
      inputs are deleted rather than left silently ignored. `preview_rejection` and
      `SchedulingService.decide` had hand-rolled `startswith("agent:")` checks that accepted the
      empty string; both now use the one shared gate.
- [x] **Approver-role table** (`APPROVER_ROLE_HOLDERS` + `validate_approver_coverage`): three
      approver roles (`engineering_lead`, `recruiter_lead`, `data_protection`) had no corresponding
      `RoleId`, so no configured principal could hold them. Enforcing `assignee_role` without this
      table would have made erasure approvals and engineering-lead sign-offs undecidable except by
      an admin. An undecidable approver role is now a startup error, not a stuck queue.
- [x] `ApprovalEngine.reassign()` — the audited escape hatch for a mis-routed approval. A reason is
      mandatory: a reassignment with no stated justification is indistinguishable, to a later reader
      of the chain, from moving an approval to someone friendlier.
- [x] **The people workspace takes its actor from the principal, not the body** — `EmployeeService`
      (create, contact update, status transition, employee documents, document verification,
      org-unit creation), `ContractService`, `TaskEngine` and `StageTransitionService` all take
      `actor: ActorRef`; the `people` and `applications` routers pass `ActorDep`. Ten actor fields
      removed from the request schemas. The dashboard's document-verifier input is deleted, so a
      person can no longer sign off a legal document under someone else's name.
- [x] **A blank actor can no longer be constructed.** `ActorRef.legacy("")` raises, because
      `AuditActor.actor_id` has `min_length=1` and a blank actor could never have been written to
      the chain anyway — the old failure mode was a state change followed by a failed audit append.
      Two tests that used to assert "the gate rejects `\"   \"`" now assert the stronger property.
- [x] **Two scheduled sweeps stop claiming to be people.** `ContractService.refresh_status` and the
      task/approval fan-out in `scheduler` recorded the bare string `"system"`, which read on the
      chain as an unclassified legacy value. They now record `ActorRef.system("scheduler")`.
- [x] **The remaining groups take their actor from the principal too** — offers,
      onboarding, offboarding, leave, growth, payroll, rate tables, compliance, and the
      approval endpoints themselves. **70 service parameters and 60 request-schema
      fields** are gone; 69 endpoints take an `ActorDep`. `POST /v1/approvals` and
      `POST /v1/approvals/{id}/decide` were the last holdout and B2 had skipped them:
      deciding an approval was still attributable to any name in a body, which is the
      single most consequential version of the hole this block exists to close.
      `GET /v1/compliance/audit/verify?checked_by=` was the last one reachable *outside*
      a body, and the dead `AuditVerifyRequest` schema it belonged to is deleted. The
      dashboard loses five more name inputs. An audit of the generated contract
      confirms that none of the 86 request schemas references an actor field, while
      the 24 response fields that record who acted are untouched.
- [x] **The named-human gates are now reached only where an actor can be one.**
      Thirteen HTTP tests that asserted 403 or 409 for an "agent actor in the body" are
      obsolete: a request cannot name an actor, so they assert **422 naming the field**
      — the stronger property, since the field is refused rather than ignored. The gates
      themselves live at the service layer and in `tests/test_named_human_gates.py`.
      One new test configures a principal whose `actor_id` is `agent:hr_bot` and proves
      it still cannot set a leave policy or decide an approval: authentication
      establishes *who*, it does not make an agent a person. That test is also what
      keeps the routers' 403 branches from rotting into dead code.
- [x] **`ActorRef.require_human_or_system`** for the one consequential operation that
      legitimately runs unattended: the retention purge. Tightening it to a
      human-only gate would leave expired records in place because nobody was
      watching. The four `system`-actor purge tests are preserved unchanged.
- [x] **`HRAGENTS_ACTOR_NAME` is in `LEAKY_ENV_KEYS`.** It names the local operator and
      therefore the actor on every audit entry an unconfigured test install records, so
      a developer's local `.env` would have failed every `== "local-dev"` assertion for
      a reason unrelated to the code under test.
- [x] **Provenance reaches the whole chain.** Every `_record` helper now calls
      `ActorRef.coerce(actor).audit_actor()`, so growth, offboarding and compliance
      entries carry provenance and role like the rest. `ApprovalEngine._record` defaults
      to `ActorRef.system("approval-engine")` for its own SLA sweep, and
      `offers.expire_overdue` no longer writes the bare string `"system"`.
- [ ] **Bind approval decisions to `assignee_role`** — `decide` checks that the actor is a human,
      but not that they hold the role the approval is assigned to, so a `MANAGER` can decide a
      `FINANCE`-assigned payroll sign-off. The table exists (see above); enforcement does not.
      Also lands here: **`RateTableService.verify` has no named-human gate**, so an agent can
      certify a BPJS or PPh21 table today. The endpoint is already behind `RATES_VERIFY`, so
      the check is the only thing missing.
- [ ] **Fix the 68 write endpoints guarded by a READ permission** and wire the 6 dead permissions
      (`PEOPLE_WRITE`, `PAYROLL_WRITE`, `COMPLIANCE_WRITE`, `RATES_VERIFY`, `AUDIT_READ`,
      `ADMIN_MANAGE`).
- [x] **Type errors once**: `api/problem.py` owns a `ProblemCode` vocabulary and a central status
      map, replacing `if message.startswith("unknown")` and 29 per-router `_not_found` /
      `_conflict` / `_forbidden` / `_bad_request` copies with one shared implementation.
      Responses now carry a stable `code` and a `type` URI derived from it, `RequestValidationError`
      has a `problem+json` handler at last, and `ERROR_RESPONSES` declares the shape on every router
      so the generated client carries the `ProblemCode` union (1602 typed error responses).
      `title` is unchanged, so nothing a human reads regressed and the 21 tests asserting message
      wording still pass. **Still open:** the prose sniffing in the routers is still there — the codes
      are available to retire it, the mechanical adoption is not done.
- [~] **Typed domain exceptions.** `Named human required` is a code now, but the branch that
      *detects* it still sniffs `"named human" in message` at 25 sites, because no exception
      carries a code yet. There is no common base class: 34 domain errors are flat
      `RuntimeError`/`ValueError` subclasses, so a single handler cannot discriminate. Next step is a
      `DomainError` base (or a registry keyed by class), then each raise-site names its own code.
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

- [~] **Postgres-backed persistence for the new surfaces.** Most in-memory stores have a
      Postgres adapter behind the same interface, selected by `HRAGENTS_STORE_BACKEND`;
      the adapter suite runs on SQLite locally and PostgreSQL in CI. This item was
      previously ticked `[x]` on the claim that *every* store had an adapter. That was
      false: five services held their state only in a Python dict, so a restart lost
      leave requests, payroll runs, onboarding templates and plans, the Ask HR chat
      transcript, and cross-workspace requests. All five are now adapter-backed
      (migrations `0014`-`0017`); §0.3 is what remains of the wider problem.
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

## 0.3 Persistence for the stateful services

> **Why this mattered.** The dashboards for leave, payroll, offboarding and Ask HR all read
> these stores. A container restart, a worker recycle or a second replica silently emptied
> them, and the product's central promise -- every decision reconstructible -- did not
> survive a deploy. This was data loss, not a missing feature.

Found by reading the services rather than the docs. Each held its state in an in-process
dict and had no Postgres adapter, so the `HRAGENTS_STORE_BACKEND` switch did nothing for
them. All five are now adapter-backed, selected by that same switch:

| Service | Adapter | Migration | Blast radius when it was lost |
|---|---|---|---|
| `ConversationStore` | `DbConversationStore` | `0014` | an answer the employee was given could not be shown again |
| `WorkspaceRequestStore` | `DbWorkspaceRequestStore` | `0014` | a handoff vanished mid-workflow |
| `LeaveService` | `DbLeaveService` | `0015` | balance adjustments and the holiday calendar silently wrong |
| `PayrollService` | `DbPayrollService` | `0016` | **a payroll was recomputed from different rate tables** |
| `OnboardingService` | `DbOnboardingService` | `0017` | a waived step came back as an unresolved blocker |

Two of these lose *silently*, which is why they got the most attention. A lost leave
request is visible -- the employee's list is empty and they file it again. A lost balance
adjustment still reads plausibly, and a lost holiday calendar makes `working_days` count a
public holiday as a working day. Nothing reports either.

Remaining in this area:

- [x] **Tenant indexes on every RLS table.** All 45 tables now index `tenant_id`, and the
      index is attached by `db.base.ensure_tenant_indexes()` as the mappers configure rather
      than declared per table, so a table added later cannot miss it. Migration `0018`
      brought the 35 older tables into line; `tests/db/test_tenant_indexes.py` is the guard.
- [ ] **Payroll runs are not immutable.** A computed run can be recomputed in place, so
      `rate_table_ids` and the figures change after a human has seen them. A re-run should
      supersede the run, not rewrite it.
- [ ] **A cancellation reason reaches the audit chain and nowhere else.** `PayrollRun` has
      no `cancelled_at`/`cancel_reason`, so the XLSX review packet shows a cancelled run's
      status without saying why. The payroll adapter deliberately did not invent the
      columns.
- [ ] **No pagination on 43 of 45 list endpoints**, and most DB lists are
      `select(Table)` with no `LIMIT` followed by a Python `sorted`. `active_plans` and
      `_previous_run` are the two aggregations that now read a whole tenant's rows.
- [ ] **No optimistic concurrency.** `db/mapping.py` read-modify-writes with no version
      predicate, so two concurrent `complete_step` calls lose one; a mid-loop erasure
      failure leaves a half-erased state.
- [ ] **No `CHECK` constraint exists anywhere in the tables.** The payroll money columns
      are `Numeric(18,2)` so the database rejects a third decimal place, but no other
      invariant is enforced below the application.

---

## 0.2 Scoring generalization to non-engineering roles

> **The single most commercially damaging defect, and it is silent.** The four
> dimensions are a backend-engineer rubric promoted to a universal schema. Worked
> example with the code as written: an 8-year accountant with an ACCA membership
> applying for a Finance Supervisor role scores `S_tech ≈ 0.58` → the sub-floor
> band. `systems_literacy` matches only `{database, devops, cloud, systems, data}`
> and 15 engineering keywords; the seniority tiers are engineering words, so
> "Accounting Supervisor" matches none.
>
> The name-swap fairness harness **cannot** catch this: swapping a candidate's
> name does not change the shape of the score distribution. It proves the
> arithmetic is invariant; the risk is in the *extraction* and the *rubric*.
>
> **What has changed.** Two things, and they are different.
>
> The sub-floor band no longer auto-rejects. `REJECT_AUTO` now maps to
> `Recommendation.REJECT_REQUIRES_SIGNOFF`, and `RecruitingService._require_rejection_proof`
> refuses to emit rejection communications until a named human has recorded a decision.
>
> The **rubric** is now per-family. `services/dimensions.py` holds a `DimensionTemplate` for each
> `JobFamily` (engineering, finance, education, healthcare, legal, operations, sales, general),
> selected by `JobSpecification.job_family`, which defaults to `ENGINEERING` so every job created
> before the field existed is scored exactly as it was. The measured failure profile — an eight-year
> accounting supervisor matching 4/4 stated requirements, `systems_literacy` **0.000**, `S_tech`
> 0.5425 → `REJECT_AUTO` — now scores 0.737 and is routed to a person.
> `tests/services/test_scoring_families.py` is the guard, built on realistic per-occupation evidence
> that the calibration corpus does not contain; the corpus and the exact-arithmetic assertions in
> `test_scoring.py` are the guard that engineering did not move.
>
> **What is deliberately unchanged.** The axes are still S ∈ [0,1]^4. A template varies *which evidence
> counts*, not how many dimensions there are, because those four names are persisted in `evaluations`,
> published in the OpenAPI document, rendered in the dashboard and translated in two locales. Turning
> the dimension *list* into data is still open below.
>
> **Measured baseline** (`evals/scoring_calibration.py`, synthetic, four
> occupations × strong/adequate/weak plus a tenured misfit each). `S_tech`:
> strong `0.777`–`0.830`, adequate `0.614`–`0.659`, weak `0.023`–`0.083`.
> Two things worth reading before touching any threshold:
>
> - **`AUTO_SCHEDULE` (`S_tech ≥ 0.85`) is a dead band.** The best matched profile
>   in the corpus reaches `0.830`. Nothing in the corpus, or in any plausible
>   profile, crosses it, so in practice every candidate is either routed to a
>   person or flagged. This is safe now that the floor prompts for sign-off, but
>   the automation the product describes does not fire.
> - **Tenure can outweigh fit.** For teaching, a tenured misfit (`0.732`) scores
>   *above* an adequate match (`0.614`). The education template now puts `0.65` of its depth weight
>   on tenure and zeroes `projects` and `publications`, which *increases* the risk rather than
>   removing it: for a family with no rich evidence model of its own, tenure is the only signal
>   available. This is the open problem below, and it is not solved by per-family templates.

- [x] **`DimensionTemplate` registry keyed by job family** — `services/dimensions.py`, eight families,
      selected by `JobSpecification.job_family`. Every family declares its competency areas, signal
      keywords, title ladder, depth vocabulary, breadth saturation and internal weights; `JobFamily` is
      checked against the registry at import so a family cannot fall back silently.
- [ ] **`DimensionTemplate` as data, not code**: `{job_family, dimensions: [{key, weight, scorer,
      evidence_requirement}], thresholds}` — versioned, audited, and snapshotted into every
      evaluation. The scorer stays deterministic; only the dimension list becomes data.
- [ ] **Version and snapshot the rubric on the evaluation.** `evaluations` records which rate tables
      a payroll used; it records nothing about which rubric scored a candidate. A template edited next
      month makes last month's `S_tech` unreproducible, which is the same failure the payroll rate-table
      provenance work fixed for money.
- [ ] **Composable primitive scorers with per-family taxonomies**: `evidence_count`,
      `evidence_density(taxonomy)`, `tenure_saturation(cap)`, `credential_registry(family)`,
      `title_seniority_tiers(family)`. A single per-family keyword taxonomy is the change that makes
      the model general.
- [ ] **Tenure must not outweigh fit.** The remaining construct-validity problem: with no rich evidence
      model for a family, tenure becomes the default answer. Needs a role-specific sufficiency test
      ("has this person actually done this job") scored independently of how long they have been
      employed.
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
      `docs/api/openapi.json`; the legacy YAML fragment is removed)
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
- [~] Leave workspace: board (who is out, per-employee balances) + queue (pending-first
      requests, cancel with a reason). Decisions are **not** here — they go through the
      approvals inbox, so this surface never offers approve/reject
- [~] Payroll workspace: runs board, run detail splitting blocking anomalies from advisory
      ones, lifecycle-gated compute/submit/cancel, review-packet link (XLSX is review only and
      the "no payments executed" notice is rendered in the UI). Approve/decline is the
      approvals inbox's job, and cancel still needs a real reason typed in
- [x] Growth workspace: board (cycles in flight, the server's overdue list, open goals with
      progress) + queue (the caller's own forms with a real rating form gated on the cycle's
      scale, and the summary draft → human-finalise editor: only employees with a submitted
      form appear, the final text box starts empty, and a finalised summary offers no button
      again). Still missing: reminder-runner visibility
- [~] Offboarding workspace: departing board, per-plan checklist (required vs optional),
      asset return/missing, finalise gated on outstanding required steps **and** asset
      clearance, start-another form whenever plans already exist. Waiving is two-step and
      requires a reason
- [x] Compliance workspace: board (unverified rate tables, open breaches, overdue breach
      steps, and an audit-chain verifier that names the session that ran it) + queue
      (consent registry with refusals recorded and withdrawal behind a mandatory reason,
      erasure requests, breach containment, retention scan, rate-table verification, and a
      purge that previews on the same code path and runs only against a typed phrase).
      Submitting an erasure raises an approval and only an approved request offers Execute;
      the decision itself is never made on this surface
- [x] Approvals workspace: board (overdue-first queue, escalate-overdue, the viewer's own
      role) + queue (approve/reject, with the reason a rejection demands and the reason a
      decision is unavailable named in words). Every department queue defers here instead
      of carrying its own approve button
- [x] Audit viewer: `GET /v1/compliance/audit/entries` (newest first, exact-match filters,
      inclusive window, limit capped at 500) + the trail panel: search the chain, read the
      recorded payload verbatim, and export the fetched slice as JSON that says it is a slice

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
