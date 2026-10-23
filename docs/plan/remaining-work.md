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
- [x] **Bind approval decisions to `assignee_role`** — `ApprovalService.decide` now calls
      `_require_authority`, which reads `may_decide_for` over `APPROVER_ROLE_HOLDERS`, so a
      `MANAGER` can no longer decide a `FINANCE`-assigned payroll sign-off; `tests/services/test_approvals.py`
      has the by-role cases. `RateTableService.verify` also insists on a named human now, which
      was the last gap in that module.
- [x] **Fix the 68 write endpoints guarded by a READ permission** and wire the dead permissions.
      `tests/test_route_inventory.py` asserts the read-guarded write set is empty and that the
      extractor still sees every module. `PEOPLE_WRITE`, `PAYROLL_WRITE`, `COMPLIANCE_WRITE`,
      `RATES_VERIFY` and `RUBRICS_VERIFY` are all used by routers now. `AUDIT_READ` guards the
      audit-trail router, so reading the raw chain is grantable without the rest of compliance
      access, and `ADMIN_MANAGE` guards the ops dead-letter surface.
- [x] **Type errors once**: `api/problem.py` owns a `ProblemCode` vocabulary and a central status
      map, replacing `if message.startswith("unknown")` and 29 per-router `_not_found` /
      `_conflict` / `_forbidden` / `_bad_request` copies with one shared implementation.
      Responses now carry a stable `code` and a `type` URI derived from it, `RequestValidationError`
      has a `problem+json` handler at last, and `ERROR_RESPONSES` declares the shape on every router
      so the generated client carries the `ProblemCode` union (1602 typed error responses).
      `title` is unchanged, so nothing a human reads regressed and the 21 tests asserting message
      wording still pass. All the prose sniffing in the routers went with the domain-error work
      above: the codes exist and every router uses them.
- [x] **Typed domain exceptions.** `hr_agents/errors.py` has the `DomainError` base every service
      error inherits (additively -- they keep `RuntimeError`/`ValueError`, so existing handlers
      still catch them) and it carries a `DomainCode` plus the status, which
      `api/problem.domain_problem` maps onto `ProblemCode` in one table. **No router recognises a
      failure by reading its message any more.** `require_named_human` decides the 403 and the code
      once; 31 record-lookup refusals across twelve services are tagged `UNKNOWN_RECORD`/404 at
      their raise sites; the override role checks are tagged `permission_required`/403; and the
      compliance `_raise` helper, which tested one shared string for every endpoint, now delegates.
      Two refusals are deliberately *not* 404: `unknown decision {decision!r}` in offers and
      `unknown step ... in plan` are validation errors, so a missing record would be a lie.
      `tests/api/test_domain_errors.py` fails if any of the three prose shapes returns.
- [x] **`Decimal` money with `ROUND_HALF_UP`**; the 173-hour divisor and 1.5×/2.0× overtime
      multipliers come from verified rate tables; progressive PPh 21 TER brackets; `absence_days`
      proration; and totals-equal-lines is an enforced invariant (commit `9cca50a`).
- [x] **Business dates in WIB**: `HRAGENTS_TIMEZONE` (default `Asia/Jakarta`) is read in one place
      (`models/common.py`: `business_today`, `business_timezone`), and all 28 `date.today()` calls in `src/` now go
      through it -- models, services and the API alike. Tests anchor to the same helper,
      `Settings` refuses an unknown zone at startup, and a guard test fails if `date.today()`
      comes back. The boundary is pinned by construction: 16:59 UTC is the 1st in Jakarta,
      17:00 UTC is already the 2nd
- [~] **A unit of work with optimistic concurrency.** The lost-update guard ships for the
      mapper-backed stores (employees, documents, contracts, approvals, tasks, rate tables,
      consent/retention/erasure/breach, review cycles/assignments/summaries, goals, and the
      offboarding tables): every tenant table carries a `version` column (migration
      `0020`), `save_model` refuses to overwrite a row that moved since the copy was
      read, and the refusal leaves as a 409 `stale_write` through a global DomainError
      handler so no router has to learn about it. Two writers who both read and both save now
      get a conflict instead of the second silently winning. The custom adapters share the
      same check through `db.mapping.check_version`; onboarding (checklists), leave
      (requests, and policies whose JSON blob carries its version in the column beside it),
      payroll (runs -- a stale recompute can no longer overwrite an approved run), applications
      (two screeners dragging one card), offers (a stale copy cannot reopen one already
      acted on; revisions stay append-only and unversioned), recruiting (job specs,
      evaluations, feedback reports, proposals and communications) and workspace/chat
      (conversations -- where a stale transcript write would erase a turn somebody watched
      arrive -- and the handoff queue). **Every persist path with a model to carry a version
      is guarded.** Three set-whole writes keep last-write-wins and say so rather than being
      silently claimed: leave balance adjustments, the holiday calendar and interviewer
      availability. The "one transaction per service method" half is still open, but the
      erasure half is no longer a silent half-state: a purge handler that raises is isolated
      (the sweep continues past it), the record is left unpurged so the next sweep retries it,
      the failure is reported in the purge report and on the compliance screen, and the audit
      chain records it. True atomicity still needs one transaction across the stores, which
      the handlers do not share.
- [x] **Schema integrity.** Migrations `0022`–`0026` added named foreign keys for every
      reference the services already guarantee (the one deliberate exception,
      `scheduling_availability.interviewer_id`, is recorded under the reference-integrity
      item above), `0023` pinned 38 CHECK constraints mirroring the model validators, and
      every pushed-down list read now orders in SQL (see the pagination item below).
- [~] **Real purge handlers and a fed retention ledger.** Four entities are done and
      the fifth is a deliberate decision. The ledger is fed by the services that
      create records: employee creation, document upload, and application submission
      (a system actor -- ingestion is machine-facing) register `employee`,
      `document` and `candidate` rows. Handlers: employee anonymize blanks
      the personal fields and keeps the row the dependents point at; a `delete` that
      would cascade-destroy history is carried out as anonymize (employee) or a soft
      delete (candidate, via `candidates.deleted_at`) with the substitution recorded;
      document purge deletes the rows; and the application handler reports that its
      rows name nobody -- the person lives on the candidate row and the consent
      registry -- so a sweep never logs a missing handler and never deletes a funnel
      entry out from under its evaluations and offers. Payroll records are
      pseudonymized rather than skipped (the decision this paragraph used to defer):
      the purge blanks the employee's name on the line while keeping amounts, ids and
      the period, because a run is a tax record and the ledger must still add up; the
      run is fed at export, so the pseudonymous line is what the ledger sees.
- [~] **Consolidate the audit and transition shapes.** The triplicated approval→status sync is
      now one `ApprovalEngine.decided(approval_id, error=..., allowed=..., subject=...)`
      accessor: it owns the shaped 404, the terminal-outcome check and the named-decider guard,
      and leave, payroll and compliance call it instead of reading the engine's private store.
      Remaining: the 13 `_record` methods, the six state-transition formats, and the declarative
      state machine behind them.

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
- [x] **Payroll runs are immutable once computed.** `set_inputs` and `compute` now accept
      only a draft or assembling run; a reviewed run answers 409 and names the replacement
      path. `supersede_run` creates a successor linked by `supersedes_id` (migration `0028`,
      self-FK) that copies the period, kind and inputs and returns in `assembling` for edits;
      the reviewed run becomes terminal `superseded` and keeps every line, figure and
      rate-table id. The audit chain records both sides of the link, the XLSX review packet
      prints the replaced run id, and the web queue labels duplicate periods by status and
      offers the reason-gated re-run action.
- [x] **A cancellation reason reaches the audit chain and nowhere else.** `PayrollRun` now
      carries `cancelled_at` and `cancel_reason` (the model refuses half a
      cancellation), `cancel_run` records both, the run view exposes them, the XLSX review
      packet's Run info sheet prints them, and migration `0019` adds the columns. A
      cancelled run is no longer a status with no why wherever it is read.
- [x] **No optimistic concurrency.** Every tenant table now carries `version` (migration
      `0020`), `Versioned` models exclude it from dumps, every persisting adapter raises
      `StaleRecordError` -> 409 `stale_write` naming both versions when a caller writes a
      row someone else changed. Set-whole writes (leave balance adjustments, holiday
      calendar, interviewer availability) are deliberately still last-write-wins; the
      erasure half-loop atomicity is tracked under the unit-of-work item below.
- [x] **Pagination.** Every list route answers the `Page[T]` envelope (`items`/`total`/
      `limit`/`offset`, shared `PaginationDep`, `limit` ≤ 200 default 100): 49 routes across
      fifteen routers, with stable id tiebreaks wherever a sort key could tie so OFFSET slices
      cannot shuffle or skip rows. The web walks pages via `fetchAllPages` so no screen
      silently truncates, and `/v1/queue` keeps its own envelope until it can move to cursor
      paging. OpenAPI + generated TS client regenerated; the api suites assert slicing,
      constant totals and 422 bounds.
- [x] **List reads materialise whole tables.** *Done for every table that grows with the
      business; the bounded and computed lists are deliberately in-Python and named here.*
      Pushed-down reads run their predicates, ORDER BY, LIMIT/OFFSET and count in one
      transaction, with the in-memory stores mirroring the contract and an id tiebreak
      wherever keys can tie: employees, leave requests (employee and pending), the leave
      calendar day window, approvals, the document vault, audit entries, payroll runs,
      applications (job/status, priority order), candidate communications and replies,
      offers (application filter), scheduling proposals, tasks (open set and overdue rank),
      contracts (expiry window), review cycles, assignments (cycle/reviewer, pending-only),
      summaries, goals (owner/status/past-due), consents, retention records (subject/entity
      and the purge gate), erasure requests, breach incidents, and offboarding assets
      (employee/plan and the clearance set). The two worst aggregations also moved:
      `_previous_run` is an ordered range scan with an existence check, and
      onboarding/offboarding active plans filter, order and slice in SQL.
      Deliberately still Python-side: operator-managed lists bounded by configuration
      (retention policies, leave policies and balances, rate tables, org units, onboarding
      and offboarding templates, job specs); employee-scoped vault/contract lists (bounded
      by one employee's record); computed lists that merge or derive rows (the compliance
      calendar's derived-deadlines-plus-operator entries, overdue breach steps, the ops
      dead-letter envelope, POST sweep results); and workspace handoffs, whose store has no
      database adapter yet.
- [x] **No `CHECK` constraint exists anywhere in the tables.** Migration `0023` pins 38
      constraints onto the tables, every one mirroring an existing model validator: the
      payroll money columns are non-negative and the four `PayrollLine` arithmetic
      identities (gross, deductions, net, employer cost) hold in SQL — rounded to the
      money quantum so SQLite's float-backed `Numeric` agrees with Postgres' exact one;
      leave days and date order; goals progress 0–100; cycle period and rating-scale
      order; finalized summaries name their text and author; employees' probation and
      offboarding dates; the four contract rules (end after start, PKWT requires an end,
      probation after start, probation only on PKWTT); approval decider pairing and
      escalation counters; retention windows, hold-reason and hold-not-purged; erasure
      consent counts; communication send attempts; evaluation score ranges; offer
      revision indices. `tests/db/test_check_constraints.py` proves the database refuses
      each family with the model bypassed.
- [x] **Eight tables had no foreign keys.** Migration `0022` adds thirteen explicitly
      named FKs: growth cycle references, the three `approval_id` columns, the
      onboarding/offboarding template and parent references, the offboarding final pay
      run, and the schedule-proposal self-reference. Wiring them exposed and fixed two
      latent crashes: nested `Decimal`/date scalars in JSON-column payloads, and the
      DB-backed audit chain storing payloads the hash had canonicalised as strings.
       Migration `0024` then closed the growth employee references: `GrowthService` now
       resolves the employee at assignment/summary/goal creation and answers a shaped
       404, so the FK guards a path that already behaves (the defensive read for a goal
       whose owner is gone — a restore-only state — keeps its test, built through the
       store). Migration `0025` closed `leave_requests.document_id`: it can only name an
       `employee_documents` row on the requesting employee's own vault, which
       `LeaveService.request` now checks, with `ON DELETE SET NULL` so retention purges
       can still delete the file. Migration `0026` closed `evaluations.application_id`
       (`ON DELETE SET NULL`; the pipeline worker already validated the application).
       One reference stays deliberately loose and is named here:
       `scheduling_availability.interviewer_id` — there is no interviewer table to point
       at. Availability belongs to a *calendar identity* (an email or provider id) that
       the scheduling integration owns, not necessarily to an employee, so validating
       it against `employees` would refuse legitimate external interviewers. The FK
       waits for whatever interviewer directory the calendar integration ships.

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
- [~] **`DimensionTemplate` as data, not code.** The template itself is now operator data:
      `rubric_versions` stores full canonical payloads, drafted, verified by a named human with
      a source note behind `rubrics:verify`, activated one per family, audited, and resolved by
      the pipeline with the code template as the fallback. The stored digest is what an
      evaluation snapshot cites, so an old score resolves to the exact payload. What remains of
      the item: the four-axis *list* is still fixed (`ScoreDimension` is persisted, published
      in OpenAPI and rendered in two locales), so a family can change what counts as evidence
      but cannot add a fifth axis. Routing thresholds now travel in the verified version payload
      (the digest covers them); `None` keeps the deployment's configured defaults.
- [x] **Version and snapshot the rubric on the evaluation.** `RubricSnapshot` (family, a
      content-addressed sha256 digest and the canonical template JSON) is attached by the
      pipeline and persisted in `evaluations.document`, so an old score names the exact
      evidence rules that produced it. The evaluation view returns the snapshot and the agent
      tool cites family + digest. Canonicalisation sorts the frozenset-derived fields, and a
      pinned engineering digest makes a rubric edit a deliberate, visible change. Turning the
      template list itself into operator-editable data is the next item, not this one.
- [ ] **Composable primitive scorers with per-family taxonomies**: `evidence_count`,
      `evidence_density(taxonomy)`, `tenure_saturation(cap)`, `credential_registry(family)`,
      `title_seniority_tiers(family)`. A single per-family keyword taxonomy is the change that makes
      the model general.
- [ ] **Tenure must not outweigh fit.** The remaining construct-validity problem: with no rich evidence
      model for a family, tenure becomes the default answer. Needs a role-specific sufficiency test
      ("has this person actually done this job") scored independently of how long they have been
      employed.
- [x] **Evidence-first scoring, with a deliberate calibration.** Every dimension carries the
      references that produced it (deduplicated, bounded), and a dimension with **no** reference
      now contributes **0** with that stated in its rationale — a senior title or long tenure is
      not evidence by itself. The policy engine pairs this with the missing-evidence bar in both
      directions: insufficient evidence cannot auto-schedule (existing) and cannot auto-reject
      (new), because the score fell for an extraction gap, not for the candidate. Both routes go
      to `HITL_MANUAL`. The decision table and formulas in `docs/architecture/hitl-bounds.md` are
      updated; the calibration corpus carries provenance so it measures the weights, and the
      engineering vector is pinned as a serialized snapshot.
- [ ] **Real credential registries per family** (BNSP, AWS/Google/Azure, ACCA/CPA/CFA). Today
      `verify_credential` is a dict lookup with no data, so a genuine certificate and a Coursera
      badge score the same.
- [x] **Per-family templates, pinned.** Templates ship for all eight `JobFamily` values
      (`engineering`, `finance`, `education`, `healthcare`, `legal`, `operations`, `sales`,
      `general`; admin- and support-shaped jobs live under `general`/`operations`), each with its
      own breadth vocabulary, signal keywords, title tiers and weight mix. Thresholds travel in a
      verified rubric version's payload, so changing bands is the same named-human act as changing
      a statutory rate. The engineering template is pinned twice: its rubric digest, and a
      serialized score vector (`test_the_engineering_scores_are_pinned_byte_for_byte`), so any
      drift is a visible, deliberate edit.
- [x] **The auto-schedule gate is evidence-aware.** Clearing `S ≥ 0.85` with `σ ≤ 0.05` no longer
      schedules if any dimension carries no `EvidenceRef`: it routes to `HITL_MANUAL` with that
      reason. Zero non-calendar flags and the run-agreement σ remain conditions. The evaluation
      table shows each dimension's run agreement (σ) and the rubric family/digest, so the number is
      inspectable. `TechnicalEvaluation.runs` already refuses a single run (minimum two), so σ is
      measured rather than definitionally zero. Making a dimension *contribute score only with
      evidence* remains the evidence-first item above.
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
- [x] Component kit: base shadcn/ui set + StatusBadge/ScoreBar/EmptyState, and the command
      palette wired: Cmd/Ctrl+K (and a topbar button) opens navigation, the current workspace rooms,
      theme, language and sign-out -- deliberately no writes, because a fuzzy match plus Enter is
      how the wrong thing gets run, and no sign-out item when the install runs as the local operator

### 2.2 Shell, auth, i18n
- [~] App shell: sidebar workspaces, topbar, responsive layout; three-room layout component
      (Board / Queue / Chat) with placeholders (real surfaces land per workspace)
- [~] Auth screens: the sign-in screen, session handling and sign-out shipped. The
      dashboard gates on /v1/session, keeps the key in sessionStorage, drops it on any
      401 and returns the person to where they were after signing in. Password reset is
      deliberately absent: the credential is an API key, so the reset path is "rotate the
      configured principal", documented in deployment.md. Service accounts keep using
      keys without the dashboard
- [x] i18n from day one: English + Bahasa Indonesia locale files, language switcher, key-parity test
- [x] Accessibility: WCAG AA text contrast verified across every board in light and dark (muted ink
      darkened to `#667085`, status tone stays on the hidden glyph, inactive tabs off
      `text-foreground/60`), skip link + main landmark, keyboard traversal; token regression test
      `theme.contrast.test.ts`. The axe/screen-reader sweep stays in polish-backlog.md
- [x] Mobile-first check at 390px: every workspace board (records, compliance, payroll, leave,
      growth, offboarding, onboarding, approvals, hiring), the payroll and compliance queue
      rooms, the command palette, dialogs and the chat transcript were driven at 390px with a
      DOM overflow probe (none anywhere) and a console check. Three fixes fell out: the identity
      chip could not shrink and pushed the topbar 18px past the viewport on every page; the
      dialog primitive had no viewport-height cap, so any dialog without its own override could
      clip; chat bubbles wrap long unbroken tokens now. The chat reply itself failed on the
      zero-config upstream rejecting its ZDR header — the transcript degraded to its designed
      `role="alert"` line rather than overflowing

### 2.3 Attention-first home
- [x] "Needs you today" wired to real queues: overdue approvals, overdue tasks, open handoffs
      (role-scoped 403s are named as role-restricted; any other failure is a retryable alert, so
      "nothing needs you" is only said when every queue answered)
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
      again, plus the reminder runner: a window in days, a run, and the tasks it created --
      with the caveat that deduplication means the list is what this run added, not everything
      outstanding)
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
- [x] Install prompt: the topbar offers install only when Chromium fires
      `beforeinstallprompt`, prompts once, and disappears after `appinstalled`; Safari has no
      such event, so the button never pretends.
- [x] Push notifications: operator-generated VAPID keys (none shipped; empty keys hide the
      toggle), a per-actor subscription table (migration `0029`, RLS + tenant index), a topbar
      toggle that enables/disables this browser and sends one test notification, a service-worker
      `push`/`notificationclick` handler, and best-effort fan-out from `ApprovalEngine.create` to
      the roles that may decide the request. Delivery is out-of-band (an executor, never the
      approval path), a 404/410 prunes the dead endpoint, transient failures keep it, and the
      sender re-resolves the person's live role so a revoked key stops receiving pings. Escalated
      approvals ping the queue again with an "overdue" body; expiry is terminal and silent.
      Payloads name the subject, never the employee: a lock screen is not an access-controlled
      surface.
- [x] Lighthouse PWA + mobile performance pass (target ≥ 90 PWA score): PWA **100**,
      accessibility **100**, best practices **96** (the console 502s are the preview server
      without an API), performance **88** on Lighthouse 11 mobile throttling. Route-level lazy
      loading split the entry chunk from 891 KB to 425 KB and cut total blocking time from
      190 ms to 60 ms; the workspace chunk (187 KB) loads on demand. FCP/LCP remain around 3 s
      on the throttled profile — the next paint/bundle target, not a PWA failure.

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
- [x] `evals/profiles.py`: 18 engineering and 32 non-IT (finance, operations, sales, admin,
      customer support) profiles, EN/ID mixed, in Markdown + JSON + a real PDF rendered by a
      deterministic writer the extractor reads back
- [x] The 4 name-swap fairness pairs are embedded in the set (scoring invariance, not just the
      harness), and `scripts/run_evals.py` imports the extraction suite

### 4.2 Edge cases (~15)
- [x] Date overlap / unexplained gap; career change; overqualified; freelance history; fake
      certification; a blank (no text layer) PDF; oversize document; malformed JSON export; two
      prompt-injection CVs; and the ghost-job mismatch — all in `evals/profiles.py` and asserted
      offline

### 4.3 Suites to add
- [x] Resume extraction: structural assertions across all 50 + edge cases (offline, no real LLM)
- [ ] Feedback faithfulness: grounding validator against stored evaluations (live model)
- [x] Policy regression: threshold routing table (pure, fast, runs offline)
- [ ] Fairness: distribution monitoring on the real scoring path (not just counterfactuals)
- [ ] Keep the honest latency section in `benchmarks.md` updated (p50/p95, per-model)

**Exit criteria:** one command runs the full suite offline and live; results table committed with
latency, costs, and failure modes documented.

---

## 5. Deployment & operations (Phase 9)

**Goal:** one command to self-host, safe defaults, zero required external services.

- [x] Setup wizard (CLI + first-run web flow): `scripts/setup.py` writes the operator,
      app name, timezone, store backend, model and one role-bound admin key to `.env`
      (compose loads it via `env_file`); the empty dashboard shows a first-run card with the
      checklist and one button that seeds the onboarding/offboarding templates and empty
      rate-table shells (`POST /v1/setup/starters`). Provider connection is connect-or-skip
      by choosing the offline test model; richer org-profile and provider forms remain under
      the provider-settings item below.
- [x] One-command self-host: `Dockerfile` (multi-stage, non-root, dashboard baked in) and a
      compose stack with postgres+pgvector, redis, minio, mailpit, a one-shot `migrate` service
      the API waits on, and `scheduler`/`messaging` loops; `/healthz` + `/readyz` (per-dependency
      readiness, 503 when degraded)
- [x] Provider settings UI with health badges, env-lock indicators, masked secrets, and
      editing: `GET /v1/providers` reports the capability, provider, health, padlock and masked
      config; `PUT /v1/providers/{capability}` stores a validated selection whose config is
      sealed (Fernet, `HRAGENTS_SETTINGS_ENCRYPTION_KEY`, migration `0030`), and
      `POST …/test` probes a candidate without saving. The form is derived from the provider's
      own Pydantic model, secrets are write-only and a blank one keeps the stored value, an
      environment lock is authoritative, and the audit entry records field names only. The
      operations page renders the Configure dialog; a deployment without a key gets an honest
      read-only panel. Built services apply a change after a restart, which the API states.
- [x] Local-model mode (Ollama): `docs/deployment.md` §8 documents the fully-offline provider
      set (llm.ollama, embeddings.ollama or the no-download `embeddings.hash`,
      storage.local_disk, queue.memory, whatsapp.manual_links, calendar.manual_slots,
      Mailpit for mail) with the honest model floor and what offline mode does not do.
      Eight tests hold the section and the registry together: every id it names exists, the
      set resolves with no secret anywhere, the local LLM builds against localhost, and the
      hosted contrast (misconfigured until a key is supplied) is real
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
      `docker-compose.yml` as a 15-minute loop. A failed run can also post one Slack-compatible
      message to `HRAGENTS_SCHEDULER_ALERT_WEBHOOK` (job names and errors, never records; the
      URL is never logged); a transport failure is logged and cannot change the exit code.
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
- [~] README: the 5-minute quickstart, demo dataset and an inline Mermaid architecture diagram
      ship. Screenshots/GIF and the GitHub social preview remain.
- [ ] README "Work with the author / freelance integration" finalized (services, contact, scope)
- [ ] Demo video / GIF walkthrough (2–3 minutes: ingest → review → override → schedule)
- [x] API docs site (OpenAPI rendered by the docs site from the committed spec) + operator
      runbooks (backup, upgrade, provider failures, incident response with the breach workflow) in
      `deployment.md`
- [x] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue templates, security policy, ADRs, release
      process (landed early with the repo-infrastructure work — see `master-build-plan.md` Phase 1)
- [~] Docs site (mkdocs-material + GitHub Pages): `docs.yml` builds and deploys on every docs
      change; the site carries the architecture, deployment, API reference and ADRs. Versioned
      docs (`mike`) remain, so old releases do not keep their own site yet.
- [~] Container image on GHCR: the `image.yml` pipeline builds `linux/amd64` + `linux/arm64`,
      scans before pushing, and fails on a fixable CRITICAL. The pipeline was added after the 0.1.0
      release and its first run found a fixable CRITICAL in the 0.1.0 lockfile (certifi), so the
      0.1.0 image is superseded rather than re-tagged; the next release builds clean.
- [~] SBOM + build provenance: the pipeline attaches an SPDX SBOM and the SARIF scan result to
      the release, and buildx attaches the SBOM and max-mode provenance to the image digest. The
      0.1.0 run failed its own gate before attaching them (see above); the next release carries all
      four.
- [ ] PyPI publishing — only if a library use case appears (currently deferred)
- [ ] GitHub social preview image + demo assets (screenshots/GIF)
- [ ] Immutable releases for tags, once the release flow has settled
- [ ] Public release: GitHub tag, release notes, Apache-2.0 confirmed, reproducible build steps
- [x] **First release published.** PR #3 was re-opened to run the required CI checks (the bot
      pushed with `GITHUB_TOKEN`, whose events do not trigger workflows), passed all six, and was
      squash-merged; `release-please` then published `hr-agents-v0.1.0` with the changelog. The
      wheel and sdist were built from the tag, checked with twine, and attached. Two earlier
      release-please runs had failed on GitHub's `pullRequestsSince` scan ("Something went wrong
      while executing your query"); the next succeeded, so that is an intermittent GitHub limit,
      not this repository's configuration. `release.yml` also gained a `workflow_dispatch` path
      because bot-published releases cannot trigger the `release: published` event themselves.

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
| 4 | **Knowledge + compliance calendar** — the calendar now ships: derived deadlines (probation ends, contract expiries, document expiries including overdue) merged with operator-entered statutory dates that must name their source, month view on the compliance board, audited add/remove-with-reason (`0021`). Remaining under this workstream: the Indonesian statutory knowledge corpus | 1, 2 | The only genuinely differentiating feature for this market, and it needs no LLM |
| 5 | Evals expansion (§4) — generated 50-profile set + extraction fairness pairs | 2 | Runs offline; feeds the paper and calibrates the templates |
| 6 | Ops hardening (§5) — wizard, alerting; the demo dataset ships (`scripts/seed_demo.py`, through the real services, rate tables left unverified on purpose) | 1, 3 | Must be stable before any public release |
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
