# Polish Backlog — deferred optimization work

**Purpose:** everything we deliberately defer while widening must land here, or it is lost.
This is the worklist for the final hardening phase (performance, security, beauty, reliability,
docs). Nothing here is a feature — if it is missing functionality, it belongs in
`remaining-work.md` instead.

**Status:** active · created 2026-09-12 · entries are added the moment a deferral is made.

Legend: `[ ]` open · `[~]` partially addressed · `[x]` done.

## Performance

- [ ] Database: index review per hot query (approvals by role+status, tasks overdue, queue scans,
      evaluations by application, audit_log by sequence)
- [ ] Pagination on every collection endpoint (jobs, approvals, tasks, audit entries, calendar)
- [ ] Home attention lists: cap + "view all" once queues grow; virtualize long lists
- [ ] Home: surface role-scoped 403s as an explicit "not available for your role" state
      (today they degrade silently to empty sections)
- [ ] N+1 audit of DB adapters once Postgres persistence lands (eager loading for timelines)
- [ ] LLM latency: batch/strip extraction prompts; consider parallel k-run scoring vs sequential
- [ ] Cache policy: skill registry fingerprint, rate tables, provider health (TTL + invalidation)
- [ ] pgvector: HNSW/IVFFlat index parameters tuned against real corpus sizes
- [ ] Web bundle: route-level code splitting, icon tree-shaking, Lighthouse budget
- [ ] Ingest path: streaming hash + parser short-circuit for oversize documents

## Security maximization

- [ ] Rate limits (per API key and per IP) on public surfaces; stricter on uploads and auth
- [ ] Key management: rotation procedure for API keys and provider credentials; kid metadata
- [ ] Upload scanning hook (ClamAV/YARA adapter) behind the storage provider
- [ ] Pen-test checklist executed against a staging instance; findings triaged here
- [ ] RLS policy audit once tenancy lands (every table, every role, negative tests)
- [ ] Log-redaction pass: fuzz `mask_secrets` with real provider payloads; audit every logger
- [ ] Dependency scanning cadence (Dependabot + periodic `uvx pip-audit` on lockfile)
- [ ] Session/auth hardening review (cookie flags, CSRF strategy for the SPA, API key scopes)
- [ ] ZDR verification note: confirm provider-side retention settings in `providers.md`
- [ ] Handoff queue reads currently require only `chat:use`; revisit per-workspace read
      permissions for `GET /v1/chat/handoffs` when the dashboard defines queue access

## Reliability

- [ ] Retry/backoff policy audit per provider; circuit breakers for flaky integrations
- [ ] Dead-letter dashboard + alerting; worker stuck-job reaper
- [ ] `/readyz` endpoint (DB + queue + storage checks) distinct from `/healthz`
- [ ] Graceful shutdown: drain in-flight pipeline runs on SIGTERM
- [ ] Backup/restore drill documented with measured RTO/RPO
- [ ] Audit chain verification scheduled + after-restore check automated

## Beauty / UX

- [ ] Chat: progressive token streaming + tool-call visibility (agent, tools read, citations) once
      the backend emits event-by-event SSE; today the client uses `POST /v1/chat` for status codes
- [ ] Motion pass (reduced-motion aware), skeleton loaders, optimistic updates where safe
- [ ] Empty states, error states, and offline states for every workspace
- [ ] Accessibility audit (axe + manual keyboard/screen-reader pass) on all workspaces
- [ ] EN/ID microcopy review with a native HR speaker; date/number/currency formatting audit
- [ ] Design token audit against `product-concept.md` §7 (no rogue colors/spacing)

## Docs & developer experience

- [ ] Docs site (mkdocs-material + Pages) with versioned API reference
- [ ] Sync `docs/api/openapi.yaml` with the Phase 5 surfaces (chat, handoffs, RBAC/tenancy
      headers); keep the live `/openapi.json` as the executable contract
- [ ] Postgres adapters for `ConversationStore` and `WorkspaceRequestStore` (in-memory
      primitives today; land with the dashboard so queues survive restarts)
- [ ] Operator runbooks: provider failures, incident response, upgrade playbook
- [ ] Reproduce benchmarks from a clean clone (script + CI artifact)
- [ ] Type strictness: evaluate `mypy --strict` on `src/hr_agents`; branch coverage 100% on
      invariant modules (scoring, policy, priority, audit, payroll gates)
- [ ] Web: storybook (or equivalent) for the component kit

## Deferred by design (do not re-litigate without demand)

- [-] Live messaging/Google/Microsoft adapters — waiting for operator credentials
- [-] Managed cloud SaaS + billing
- [-] Office Connector folder-sync agent
