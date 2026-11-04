# 08 — Feature parity plan (Rust + Tauri)

**Target:** Tauri 2.12, Rust 2024, SQLite (WAL) in the app data directory, one company per
install, 1–3 HR operators, local login. No employee, manager, finance, or candidate roles.
No multi-tenant data model, no RLS, no Docker/Postgres/Redis/MinIO, no PWA/push, no MCP
marketplace, no public webhooks. Only features that remove repetitive or exhaustive HR work.

## Rust shape

```text
rust/crates/hragents-core/   hiring · approvals · people · onboarding · leave · payroll
                             growth · offboarding · compliance · chat · scoring · policy
rust/crates/hragents-app/    use cases · transactions · audit orchestration · exports
rust/crates/hragents-ipc/    Tauri commands (one module per domain, plus setup)
rust/crates/hragents-store/  migrations · repo/* · FTS5 · backup
parity/cases/<module>/       fixtures · parity/golden/<module>/
e2e/                         journeys/*.spec.ts
```

Module paths in the matrix are logical (`hiring::jobs`, `payroll::calc`); crate boundaries
are fixed in 03. The `.rs` names are case groups replayed by `hragents-parity`. Every row
consumes `parity/cases/<module>/<case>.json` with `input`, `expected`, `error_code`, and
`audit_actions`; `scripts/parity_export.py` freezes UUIDs and timestamps. A row is green
only when the Rust command returns the same domain outcome and audit action names.

## HR-only scope

| Decision | Items |
|---|---|
| **Keep** | Hiring intake→evaluation→review→offer→comms; approvals inbox; people/records; onboarding; leave on behalf; payroll prep; growth admin; offboarding; compliance; Ask HR; email/WhatsApp/calendar. |
| **Finish** | Candidate profile + CV; document preview; payroll inputs; JKK/dependents; THR BPJS; FINAL settlement; approval deep-links; onboarding names; doc-request sync; offer→onboarding; HR-only scoping. |
| **Add** | Local login; company setup; search/command palette; inline preview; backup/restore; receipt drawer; optional demo data. |
| **Hide** | Provider breadth (short list), rubric/credential editors under “Advanced”, MCP catalog. |
| **Remove** | Employee self-service; manager/finance roles; candidate portal; multi-tenant/RLS; PWA/push; MCP marketplace/server; webhooks; Docker/Postgres/Redis/MinIO; shell tools; payment execution. |

## Parity matrix

| Python feature | Rust module | Parity test | Acceptance | Decision |
|---|---|---|---|---|
| Jobs, lifecycle, family, weights | `hiring::jobs` | `hiring_jobs.rs` | Legal status moves only; weights sum 1.0 ±1e-9 | Match |
| Intake CSV/CV, consent | `intake` | `hiring_intake.rs` | ≤500 batch; per-row reason; consent required | Match |
| Evaluation k≥3, rubric snapshot | `scoring` | `golden/scoring.rs` | Same S/σ; evidence on every dimension | Match |
| Policy thresholds/precedence | `policy` | `golden/policy.rs` | Same table; human gate on rejection ≥0.60 | Match |
| Board and transitions | `hiring::stage` | `hiring_board.rs` | Invalid move 409; named human + reason | Match |
| Review queue and overrides | `hiring::review` | `hiring_overrides.rs` | Append-only; rejection reason; receipt | Match |
| Scheduling and busy blocks | `hiring::scheduling` | `hiring_scheduling.rs` | No double-booking; human confirm | Finish |
| Offers and acceptance | `hiring::offers` | `hiring_offers.rs` | Revisions append-only; acceptance starts onboarding | Finish |
| Comms and feedback PDF | `hiring::comms` | `hiring_comms.rs` | Preview before queue; dispatch evidence; PDF matches | Match |
| Candidate profile and CV | `hiring::candidate` | `hiring_candidate.rs` | Name/contact/CV inline; no UUID label | Finish |
| Approvals, decide, escalate, sync | `approvals` | `approvals_flow.rs` | Role authority; reason; SLA; doc-request sync | Finish |
| Ask HR, citations, handoffs | `chat` | `chat_parity.rs` | Cite-or-escalate; no action; transcript persists | Match |
| Onboarding templates/plans/steps | `onboarding` | `onboarding_flow.rs` | Human-only waive; names, never UUIDs | Match |
| Onboarding docs/offer handoff | `onboarding` | `onboarding_docs.rs` | Verified doc only; one plan, idempotent | Finish |
| Directory and org chart | `people` | `people_org.rs` | Filter; roll-up; create/edit/detail | Finish |
| Contracts PKWT/PKWTT | `people::contracts` | `people_contracts.rs` | Structural rules; expiry; named act | Match |
| Vault, preview, verify | `documents` | `people_documents.rs` | Preview before verify; checksum; receipt | Finish |
| Payroll profile JKK/dependents | `people::payroll` | `people_payroll.rs` | Class 1–4, 0–20; validation; audit | Add |
| Leave policy/accrual/holidays | `leave` | `leave_policy.rs` | Same working-day math; no hardcoded rates | Match |
| Leave balances/adjustments | `leave` | `leave_balance.rs` | Entitled/used/pending; reason + human | Match |
| Leave on behalf/decide/calendar | `leave` | `leave_flow.rs` | Pick by name; balance first; pending→used | Finish |
| Payroll runs/immutability | `payroll` | `payroll_runs.rs` | Same guards; supersede; cancel reason | Match |
| Payroll inputs grid | `ipc::payroll` | `payroll_inputs.rs` | All fields; totals preview; restart-safe | Finish |
| Rates/effective date/provenance | `payroll::calc` | `golden/payroll_rates.rs` | Unverified blocks; table id per line | Match |
| BPJS/PPh21/overtime/absence | `payroll::calc` | `golden/payroll_calc.rs` | Decimal exact; totals equal lines | Match |
| THR | `payroll::calc::thr` | `golden/payroll_thr.rs` | Verified months; proration; BPJS anomaly blocks | Finish |
| FINAL | `payroll::calc::final` | `golden/payroll_final.rs` | Settlement from verified tables; missing row blocks | Finish |
| Approval and XLSX export | `ipc::payroll` | `payroll_export.rs` | Approved only; packet hash; no bank file | Match |
| Growth cycles/forms/summaries/goals | `growth` | `growth_parity.rs` | Human submit/final; append-only progress | Match |
| Offboarding plans/steps/assets | `offboarding` | `offboarding_flow.rs` | Human waive; asset blockers; finalise gate | Match |
| Offboarding final pay | `offboarding` | `offboarding_final.rs` | One FINAL run + task; idempotent | Match |
| Consent registry | `compliance::consent` | `compliance_consent.rs` | Human revoke; withdrawal blocks re-run | Finish |
| Retention/purge/hold | `compliance::retention` | `compliance_retention.rs` | Dry run = real; hold wins; honest outcome | Match |
| Erasure two gates | `compliance::erasure` | `compliance_erasure.rs` | Verify → approve → execute; dispositions | Match |
| Breach and calendar | `compliance` | `compliance_breach.rs` | Forward-only; derived + sourced dates | Match |
| Audit chain/viewer/export | `audit` | `golden/audit.rs` | Tamper-evident; receipt per decision | Match |
| Rate/rubric/credential registries | `compliance::registries` | `compliance_registries.rs` | Named verify; unverified unusable | Match |
| Setup, company, local auth | `ipc::setup`, `auth` | `setup_first_run.rs` | Company/timezone; Argon2id; lockout | Add |
| Providers/integrations | `integrations` | `provider_parity.rs` | No plaintext secrets; offline default | Finish |
| Health/dead letters/usage | `ops` | `ops_health.rs` | Local log; failures visible; cost rollup | Different |
| MCP/PWA/webhooks | — | `removed_features.rs` | Routes/screens absent from build | Cut |
| Docs/i18n/evals | `i18n` | `i18n_parity.rs` | EN/ID parity; offline corpus | Match |

## Must match vs intentionally different vs drop

**Must match:** scoring/σ/evidence; policy precedence; payroll Decimal and totals-equal-lines;
leave working days; contract rules; approval authority and human gates; audit hash semantics.

**Intentionally different:** SQLite not Postgres; local login not API keys; one HR role not five;
no tenant/RLS; no PWA/push; polling/manual dispatch not public webhooks; native preview not
browser download; navigation rebuilt around the five journeys.

**Drop:** employee self-service, manager/finance, candidate portal, multi-tenant/RLS, PWA/push,
MCP marketplace/server, webhooks, Docker/Postgres/Redis/MinIO, shell tools, payment execution.

## Five core journeys — acceptance

### 1. First run → login → company → employee → onboarding

1. Fresh install opens setup, not an empty dashboard; operator sets passphrase (Argon2id), company, timezone (`Asia/Jakarta`), currency (IDR).
2. Login is offline; five failures back off; session survives restart; sign-out clears it.
3. “Add employee” takes name, hire date, title, unit, employment type; optional email/phone/manager.
4. “Start onboarding” previews a template, creates the plan/tasks, moves the employee to `onboarding`.
5. **Pass:** under 3 minutes; no UUID typed/shown; one receipt covers employee + plan; restart-safe.

### 2. Import candidate → open CV → evaluate → gated rejection → receipt

1. Drop PDF/DOCX; original stored, checksum shown, name/contact/skills extracted.
2. Select job; evaluation runs k≥3 on the configured or offline model.
3. Detail shows name, contact, CV preview, score/evidence, policy decision.
4. Rejection stays disabled until a named human gives a reason and reads the message preview; confirm queues, never sends.
5. **Pass:** no auto-reject; candidate is never a UUID; CV opens inline; receipt survives restart/export.

### 3. Leave on behalf → balance → decide → calendar

1. HR picks the employee by name (no UUID), then type and dates.
2. Working days exclude weekends/holidays; entitled/used/pending/available show before submit.
3. Overlap, min-service, document and negative-balance rules block with a reason; the request enters approvals as `pending`.
4. Named human decides; balance moves pending→used (or back), calendar updates.
5. **Pass:** one entry screen; receipt; cancel needs reason; balance/calendar agree after restart.

### 4. Payroll run → inputs → compute → approve → export

1. Create monthly/THR/FINAL run; duplicate period warns.
2. Grid edits base salary, allowances, overtime, absence, loan, bonus, service months; JKK/dependents come from the profile.
3. Verified tables are chosen by effective date; missing/unverified blocks; compute shows BPJS, PPh 21, net, employer cost.
4. ERROR anomalies block sign-off; named human approves; export is the XLSX packet with “no payments executed”.
5. **Pass:** totals equal lines to the cent; provenance per figure; export blocked before approval; no bank file.

### 5. Document upload → preview → verify → audit

1. Drop PDF/JPG/PNG; type/size validated, checksum computed, file stored in app data.
2. Preview renders inline before any verify action.
3. Assign employee, kind, issued/expiry; labels use `business_today`.
4. Verify/reject needs a named human; rejection reason mandatory.
5. **Pass:** preview precedes verify; corrupt files refused with guidance; receipt in the audit drawer; retention/erasure honours it.

## Definition of done

- [ ] **No UUIDs in the UI.** Every entity has a human label; IDs appear only in a detail drawer with copy.
- [ ] **Every screen has one primary action.** Board and queue never dead-end; approval items land where decisions happen.
- [ ] **Every decision has an audit receipt.** Actor, role, timestamp, subject, reason, before/after; copy/export.
- [ ] **Every list has empty, loading, and error states.** A failed query is never “nothing needs you”.
- [ ] **No hidden automation.** Agents extract/communicate; deterministic code decides; a named human gates every consequential outcome.
- [ ] **Offline by default.** Only configured LLM/email/WhatsApp/calendar calls leave the machine.
- [ ] **Restart-safe.** SQLite WAL, backup/restore, no data loss on update.

## Migration gates

| Gate | Requirement | Exit evidence |
|---|---|---|
| **G0 — Parity fixtures** | `scripts/export_parity.py` captures every domain case from Python into canonical JSON; ≥200 cases; UUID/timestamp normalization reviewed | Fixture corpus committed; deterministic re-run |
| **G1 — Domain parity** | Every matrix row green in `tests/parity/`; same success shape and same error codes | `cargo test --test parity` green; diff report |
| **G2 — Golden tests** | Scoring, policy, payroll Decimal math, leave days, contract rules, audit hash chain pinned byte-for-byte | `tests/golden/` green; no tolerance beyond 1e-9 |
| **G3 — E2E** | Five journeys run on Windows via `tauri-driver` + WebdriverIO, offline, fresh install | Screenshots + receipts; zero UUID assertions |
| **G4 — Data migration** | One-way import of Python export (employees, documents metadata, leave, payroll, audit) into SQLite | Count + checksum reconciliation; audit chain verifies |
| **G5 — Cutover** | Freeze Python writes; export; import; replay G3; named sign-off; rollback path | Signed checklist; old export retained |

No row is “done” because a screen renders. A row is done when its parity test, golden test
(where arithmetic is involved), and journey step pass on a clean install.
