# 01 — Current features (Python + React)

**Scope:** `plan/desktop-rust-migration`, 2026-11-01. Inventory of what the Python/FastAPI +
React product actually does today, so the Rust/Tauri rewrite has a baseline rather than a
wish list. Read-only audit; no code changed.

**Legend:** `[x]` works end-to-end · `[~]` partial, API-only, or UI incomplete · `[ ]` missing/broken.

## Product shape

| Dimension | Count |
|---|---|
| Workspaces | **10** — Approvals, Hiring, Ask HR, Onboarding, People, Leave, Payroll, Growth, Offboarding, Compliance (`workspaces.py`) |
| Agents | **5** — resume deconstructor, code portfolio, screening coordinator, feedback writer, policy assistant (`agentset.py`) |
| API surface | **~199 paths / 239 operations** (`docs/api/openapi.json`) |
| Persistence | **45 tables · 44 migrations** per the migration brief; measured `Base.metadata` here is **55 mapped classes** (54 tenant-scoped, 89 indexes), head `0043_usage_cost` — see `04-sqlite-data.md` |
| Backend tests | **~2,200** (2,233 in README) |
| Web tests | **~450** (448 in README) |
| Containers | **9** — api, worker, scheduler, messaging, migrate, postgres, redis, minio, mailpit (`docker-compose.yml`) |

## Hiring

- [x] **Jobs** — CRUD, draft→open/paused/closed, job family, weights summing 1.0 (`/v1/jobs`, `JobManager.tsx`).
- [x] **Intake** — single CV, batch CSV/CV, consent gate, conflict report (`/v1/applications`, `ImportPage.tsx`).
- [x] **Evaluation** — guard → extraction (k≥3) → scoring → σ → policy → evidence refs (`services/pipeline.py`).
- [x] **Policy** — consent halt, anomaly, calendar, auto-schedule, soft/human-only auto-reject (`services/policy.py`).
- [x] **Board** — five stages, drag/keyboard, validated transitions, named human + reason (`PipelineBoard.tsx`).
- [x] **Review queue** — gated applications, named sign-off, append-only overrides, receipt (`ReviewQueue.tsx`).
- [x] **Scheduling** — availability, proposals, confirm/cancel/reschedule, busy-block subtraction (`SchedulingView.tsx`).
- [x] **Offers** — revisions, approval, message, acceptance/decline, expiry (`OfferPanel.tsx`, `/v1/offers/*`).
- [x] **Comms** — rejection/offer preview, email/WhatsApp/Telegram queue, dispatch evidence, replies, 72h SLA (`CommunicationPanel.tsx`).
- [x] **Feedback** — agent report or deterministic EN/ID synthesis, PDF letter (`/v1/candidates/{id}/feedback[.pdf]`).
- [x] **Inbound email drafts** — parse, confirm/discard (`/v1/applications/email-drafts`).
- [~] **Candidate identity** — detail shows `shortId(candidate_id)`, no name/contact/CV/profile; no `GET /v1/candidates/{id}` (`ApplicationDetailPage.tsx:214`).
- [~] **Offer → onboarding** — acceptance marks the offer and application; no plan is created (`services/offers.py:348`).
- [ ] **Candidate portal** — absent.

## Approvals / decisions

- [x] **One inbox** — pending/overdue queue, mandatory rejection reason, escalation, role badge (`ApprovalsWorkspace.tsx`).
- [x] **Authority** — decisions bound to `assignee_role`; a manager cannot decide a finance sign-off (`rbac.py`).
- [x] **Self-approval guard** — rejected unless `hr_admin`; shortcut visible on the chain (`services/approvals.py`).
- [x] **Subject sync** — leave, payroll, erasure, offer and scheduling reconcile via transactional outbox (`approval-reconcile`).
- [~] **Home deep-link** — approval items land in the subject queue (`/w/leave?room=queue`) where nothing can be decided; decisions live in `/w/approvals?room=queue` (`attention.ts`).
- [ ] **Manager/finance matrix** — not needed in the HR-only target.

## Ask HR

- [x] **Front door** — deterministic routing, workspace hint, safe Ask HR fallback; never executes (`services/front_door.py`).
- [x] **Grounded answers** — cite-or-escalate `PolicyAssistant`, SSE streaming, tool-call visibility (`ChatPanel.tsx`).
- [x] **Handoffs** — ranked alternates, human-invoked cross-workspace queue (`/v1/chat/handoffs`).
- [x] **Persistence** — transcripts survive restart, workspace-pinned with 409 on cross-workspace continuation.
- [~] **Knowledge surface** — chat only; no browser/editor/versioning UI.
- [~] **Intent classification** — ambiguous messages fall back to Ask HR; no classifier.

## Onboarding

- [x] **Templates/plans** — operator templates, starter draft, role/contract matching, template hash (`/v1/onboarding/*`).
- [x] **Checklist** — complete/waive/link document; required progress, overdue, blockers; waive needs human + reason (`OnboardingChecklist.tsx`).
- [x] **Document collection** — step links to vault; kind mismatch rejected; only verified doc auto-completes (`/steps/{key}/link-document`).
- [~] **Names bug** — board and checklist call `useEmployees(false)`, disabling the query; cards fall back to an 8-character UUID (`OnboardingBoard.tsx:85`, `OnboardingChecklist.tsx:148`).
- [~] **Start plan** — creates the hire inline; no full employee create/edit screen in People.
- [~] **Template editor** — no step editor; templates come from the start flow or API.
- [ ] **Contract generation, accounts/equipment** — not built.

## People / records

- [x] **Directory** — unit filter, status badges, headcount roll-up, org tree (`RecordsWorkspace.tsx`, `/v1/employees`).
- [x] **Contracts** — PKWT/PKWTT rules, probation restrictions, activate/terminate, expiry (`services/contracts.py`).
- [x] **Document vault** — metadata, expiry buckets, named verify/reject, audit (`DocumentVault`).
- [x] **Lifecycle** — onboarding→probation→active→notice→offboarded, guarded (`Employee.transition`).
- [~] **Employee detail/edit** — no detail or edit screen; creation only via onboarding.
- [~] **Payroll profile** — `jkk_risk_level`/`dependents` exist on the model but are absent from `EmployeeCreate`/`EmployeeView`; no client can set or read them (`api/people_schemas.py:38`).
- [~] **Document preview** — `/v1/documents` is upload-only; no content/download route (`api/routers/documents.py`).
- [~] **Document requests** — approval exists, but a task appears only after manual `/document-requests/{id}/sync`; no UI call, no scheduler (`services/document_requests.py:117`).
- [ ] **Private-data scoping** — `MANAGER` has `people:read`, reaching every record and document list; no per-person scoping (`rbac.py:83`).

## Leave

- [x] **Policies/accrual** — eight types, flat-monthly/lump-sum/per-event/none, min service, carryover caps, operator holidays (`services/leave.py`).
- [x] **Working-day math** — weekends and holidays excluded.
- [x] **Balances** — entitled/used/pending/carried/adjustment; manual adjustment with reason.
- [x] **Requests** — validation chain, approval routing, decision sync, cancel with reason (`/v1/leave`, `LeaveQueue`).
- [x] **Calendar** — who is out, pending-first queue, per-employee history (`LeaveBoard`).
- [~] **Record on behalf** — `POST /v1/leave` exists but the UI has no request form; the board is read-only and the queue only cancels (`LeaveWorkspace.tsx`).
- [ ] **Employee self-service** — no request screen, and the `employee` role is blocked by the router-level `people:read` guard on `/v1/leave` and `/v1/growth` before its `self_service` route check is reached; there is no employee journey.
- [ ] **LeaveAssistant** — not built.

## Payroll (prepare/verify only)

- [x] **Lifecycle** — draft→assembling→ready→pending sign-off→approved→exported; reject/cancel/supersede; computed runs immutable (`services/payroll.py`).
- [x] **Rate tables** — BPJS, PPh 21 TER/PTKP, overtime, THR formula, minimum wage; effective date; unverified blocks (`RateTableService`).
- [x] **Computation** — Decimal money, BPJS shares, progressive PPh 21, overtime per day, absence proration, THR months, minimum wage (`models/money.py`).
- [x] **Anomalies** — negative net, excessive overtime, net deviation, missing tables; ERROR blocks sign-off.
- [x] **Approval/export** — named human, XLSX packet with “no payments executed”, export gate (`/runs/{id}/packet.xlsx`).
- [~] **Inputs UI** — `PUT /runs/{id}/inputs` exists; no grid for salary, allowances, overtime, absence, loans, bonus, service months (`PayrollWorkspace.tsx`).
- [~] **THR** — reads `thr_formula`; BPJS treatment is unmodelled and raises a blocking anomaly for a human (`services/payroll.py:803`).
- [~] **FINAL** — offboarding opens it, but there is no settlement branch; it produces the monthly shape, not severance (`services/payroll.py:641`).
- [~] **Attendance** — CSV/XLSX preview/commit with mapping and holiday exclusion; no compensation master (`AttendanceImportDialog.tsx`).
- [ ] **Payslip distribution / bank file** — absent; payments happen outside.

## Growth

- [x] **Cycles** — operator scale, lifecycle guards, assignment before activation, close blockers (`services/growth.py`).
- [x] **Forms** — per-reviewer assignments, due dates, human-only submit, skip reason, workload (`GrowthQueue.tsx`).
- [x] **Summaries** — grounded draft, human-only finalisation, terminal text (`/v1/growth/summaries`).
- [x] **Goals** — title/metric/cycle, append-only progress, activate/complete/cancel, overdue (`GrowthBoard`).
- [x] **Reminders** — deduplicated system tasks (`/v1/growth/reminders/run`).
- [~] **Admin creation** — cycle/assignment/goal APIs exist; no complete create/edit UI.
- [ ] **ReviewAssistant** — not built.

## Offboarding

- [x] **Templates/plans** — reason/role matching, steps, tasks, employee moved to notice (`services/offboarding.py`).
- [x] **Exit workflow** — human-only complete/waive, interview, handover, completion gate (`OffboardingQueue.tsx`).
- [x] **Assets** — assigned→returned/missing/written-off; blockers (`AssetPanel`).
- [x] **Final pay link** — opens a FINAL run and task; no payment (`/plans/{id}/final-pay`).
- [x] **Finalise** — required steps + zero asset blockers, then employee transition.
- [~] **Template editor** — default only; no step editor.
- [ ] **Asset inventory at onboarding** — not built.

## Compliance

- [x] **Consent** — purpose grants/refusals/revocations, lawful basis, expiry, evidence, human-only revoke (`ConsentSection`).
- [x] **Retention** — policies, ledger, scan/dry-run/purge, legal holds, per-entity handlers (`services/retention.py`).
- [x] **Erasure** — verify → Data Protection approval → separate execution; dispositions (`/v1/compliance/erasures`).
- [x] **Breach** — checklist templates, steps, notifications, forward-only status, overdue (`BreachSection`).
- [x] **Compliance calendar** — derived deadlines + operator dates with `source_note` (`CalendarBoard`).
- [x] **Audit viewer** — search, filters, live verification, JSON export (`AuditTrailPanel`).
- [x] **Registries** — rate tables, rubrics, credentials behind named-human verify (`CredentialsSection`).
- [~] **Consent enforcement** — worker reads `application.consent.granted`, not the registry; later revocation does not halt a re-run (`evaluation_job.py:89`).
- [~] **Erasure atomicity** — journal/reconcile exists; one transaction across stores does not.
- [ ] **WLKP/BPJS reminders, wider labour-law KB** — not built.

## Ops

- [x] **Operations** — providers, connections, MCP, dead letters/requeue, usage/cost, fairness (`OperationsPage.tsx`, `/v1/ops/*`).
- [x] **Health** — `/healthz`, `/readyz`, `/metrics`, timing, correlation ids (`api/metrics.py`).
- [x] **Loops** — scheduler/messaging reports, healthchecks, reaper, alerts (`services/periodic.py`).
- [x] **Setup** — wizard, first-run card, starter checklists/rate-table shells (`/v1/setup`).
- [~] **MCP routes** — audit reported 404s; routes exist and are tested here (`tests/api/test_mcp_servers_api.py`). Smoke-test stale builds and `admin:manage`.
- [~] **Backup/restore** — scripted, documented, no UI.
- [~] **Observability** — metrics text only; no OTel/Prometheus/Grafana.

## Auth

- [x] **API-key auth** — role-bound principals, local-operator mode, `/v1/session`, login gate, 401 return path (`auth.py`, `LoginPage.tsx`).
- [x] **Actor provenance** — `ActorRef` records authenticated/system/agent/legacy; 401 vs 403 distinct; no body names the actor.
- [x] **Permission fence** — every write names a write/self-service permission, guarded by a structural test (`tests/test_route_inventory.py`).
- [x] **Named-human gates** — one shared gate; ten ungated operations closed (`tests/test_named_human_gates.py`).
- [~] **Account management** — principals/keys are env config; no user-management UI.
- [~] **Employee login** — `EMPLOYEE` can be bound to an employee, but there is no self-service screen or provisioning flow.
- [ ] **Local passphrase** — API keys only; desktop needs local login.

## Cross-cutting

- [x] **Audit** — hash-chained append-only log, tamper detection, decision receipts, Postgres, verifier (`services/audit.py`).
- [x] **Providers** — 21 across 10 capabilities, health checks, masked secrets, UI settings (`providers/`).
- [x] **MCP** — client, namespaced tools, destructive approval, catalog, `hragents-mcp` server (`mcp_server.py`).
- [x] **PWA** — manifest, offline shell, install prompt, push subscriptions (`features/pwa`).
- [x] **i18n** — EN + ID, key/placeholder parity test (`web/src/i18n`).
- [x] **Docs** — MkDocs, versioned API, generated OpenAPI, runbooks (`mkdocs.yml`).
- [x] **Evals** — 69 offline cases, fairness name-swap, calibration, live run (`evals/`).
- [x] **Data layer** — Postgres RLS, tenant indexes, optimistic concurrency, pagination, 38 CHECKs, named FKs (`db/`).
- [~] **LLM model setting** — `HRAGENTS_LLM_MODEL` is documented and written by setup, but `AgentRuntime.from_env()` reads only provider settings; it is inert (`agents/runtime.py:64`).

## Known P0/P1 defects

These are the audit findings that must not be re-created in Rust. Severity is product impact, not code size.

| ID | Sev | Defect | Evidence | State |
|---|---|---|---|---|
| D1 | P0 | Candidate shown as a UUID; no candidate profile/contact/CV | `ApplicationDetailPage.tsx:214`; no `/v1/candidates/{id}` | open |
| D2 | P0 | No document preview/download anywhere | `api/routers/documents.py` upload-only | open |
| D3 | P0 | Payroll has no compensation/inputs UI | `PayrollWorkspace.tsx`; API-only `PUT /inputs` | open |
| D4 | P0 | Employee payroll profile (JKK class, dependents) not exposed by API/UI | `api/people_schemas.py:38`; model has fields | partial |
| D5 | P0 | THR blocks on unmodelled BPJS; FINAL has no settlement arithmetic | `services/payroll.py:803`, `:641` | partial |
| D6 | P0 | Home approval links dead-end in a non-deciding queue | `attention.ts`; `LeaveQueue` | open |
| D7 | P1 | Onboarding shows UUIDs because the employee query is disabled | `OnboardingBoard.tsx:85`; `OnboardingChecklist.tsx:148` | open |
| D8 | P0 | Employee self-service is unreachable (no UI/account flow) | `rbac.py`; `App.tsx` has no employee routes | open |
| D9 | P0 | Consent withdrawal not enforced against evaluation | `evaluation_job.py:89` uses intake snapshot | open |
| D10 | P0 | Document requests stall after approval; sync is manual and unused | `people.py:216`; `document_requests.py:117` | open |
| D11 | P1 | `HRAGENTS_LLM_MODEL` is inert | `agents/runtime.py:64` | open |
| D12 | P1 | MCP routes reported 404; present/tested here | `tests/api/test_mcp_servers_api.py` | verify |
| D13 | P0 | Offer acceptance never starts onboarding | `services/offers.py:348` | open |
| D14 | P1 | Managers can read all employee/document data | `rbac.py:83`; no record scoping | open |
| D15 | P1 | HR cannot record a leave request in the UI | `LeaveWorkspace.tsx` | open |
| D16 | P1 | No employee detail/edit screen; create only via onboarding | `RecordsWorkspace.tsx` | open |
| D17 | P1 | Growth cycle/assignment creation is API-only | `GrowthWorkspace.tsx` | open |

**what this means: the product is API-rich but journey-incomplete.**
