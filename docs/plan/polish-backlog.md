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
- [ ] Pagination on every collection endpoint (jobs, approvals, tasks, audit entries, calendar) —
      43 of 45 list endpoints are still unbounded, and nearly every DB list is `select(Table)` with
      no `LIMIT` followed by a Python `sorted`
- [ ] Home attention lists: cap + "view all" once queues grow; virtualize long lists
- [x] Manual pipeline stage transitions on the board: designed transition policy first
      (`docs/architecture/board-transitions.md`), then dnd-kit drag with keyboard support
- [ ] Home: surface role-scoped 403s as an explicit "not available for your role" state
      (today they degrade silently to empty sections — and a 500 renders as "nothing needs you")
- [x] N+1 audit of DB adapters once Postgres persistence lands (eager loading for timelines)
- [x] **LLM latency: the k extraction runs now execute concurrently** (`asyncio.gather`) instead of
      sequentially — k runs were k× the wall clock for no added signal
- [ ] Cache policy: skill registry fingerprint, rate tables, provider health (TTL + invalidation)
- [ ] pgvector: HNSW/IVFFlat index parameters tuned against real corpus sizes
- [ ] Web bundle: route-level code splitting, icon tree-shaking, Lighthouse budget. Today one
      737 KB chunk serves the whole app, for a persona on a phone
- [ ] Ingest path: streaming hash + parser short-circuit for oversize documents

## Observability

- [x] `/metrics` in Prometheus text format (`curl` is enough, no exporter stack), with the two
      canaries that would have caught the missing worker on day one:
      `hragents_applications_stuck_queued` and `hragents_scheduler_last_success_timestamp`
- [x] Scheduler and messaging loops write a JSON report to a shared volume every tick; `/metrics`
      reads it, so a job failing inside `while true` goes stale instead of silent. Every loop
      container has a `HEALTHCHECK`
- [x] `/readyz` now checks `queue` and `skills` as well — it reports `degraded` when the product
      cannot work, not just when it cannot start
- [x] Request timing middleware with an `X-Response-Time-Ms` response header
- [x] Dead letters carry their reason: `QueueMessage.failed_reason` / `failed_at` are populated by
      all three backends, so an operator can see why a message died
- [ ] Structured logging through the service layer. Today `get_logger` is imported in exactly one
      module: 32 services, 24 routers, and every agent emit **zero** log lines
- [ ] Request/correlation id bound to `structlog.contextvars` and echoed in responses
- [ ] Dead-letter dashboard + alerting; worker stuck-job reaper
- [ ] OTel traces — declared as a dependency and never wired. Three unused packages ship in the
      production image; drop them or instrument
- [ ] Cost tracking: no `usage()` call exists anywhere, so "what did this candidate cost" is
      unanswerable
- [ ] `lizard` is a runtime dependency imported nowhere; `Settings.github_token`,
      `crossref_mailto`, and `telegram_bot_token` are read zero times yet advertised in
      `.env.example`

## Security maximization

- [ ] Rate limits (per API key and per IP) on public surfaces; stricter on uploads and auth.
      Two live defects: `request.state.actor_id` is never assigned, so the "per principal" docstring
      is false and it is per key/IP; and `X-Forwarded-For` is trusted blindly, so an attacker gets a
      fresh bucket per request
- [ ] Rate-limiter key eviction. `_hits` is only pruned on *reuse*, so rotating `X-Forwarded-For`
      grows the dict without bound — an unauthenticated memory-exhaustion vector
- [ ] Body-size ceiling is header-only. A chunked request bypasses the middleware, and
      `POST /v1/documents` does `await file.read()` before the service-level size check
- [ ] Key management: rotation procedure for API keys and provider credentials; kid metadata
- [ ] Upload scanning hook (ClamAV/YARA adapter) behind the storage provider. No MIME sniffing
      either: `kind` is a client-supplied form field, and an arbitrary binary is decoded as UTF-8
- [ ] Pen-test checklist executed against a staging instance; findings triaged here
- [x] **RLS actually applies in the shipped stack**: `docker/postgres/10-non-superuser.sql` demotes
      the image-created superuser on first init (ADR 0006 knew it was bypassed and deferred it).
      Existing volumes need the `ALTER ROLE` by hand
- [ ] Log-redaction pass: fuzz `mask_secrets` with real provider payloads
- [ ] Dependency scanning cadence (Dependabot + periodic `uvx pip-audit` on lockfile)
- [ ] Session/auth hardening review. The current state is a documented trap: no keys means
      unauthenticated `HR_ADMIN` on `0.0.0.0:8000`; keys mean the dashboard 401s because there are
      no login screens. One or the other has to be resolved
- [ ] Handoff queue reads currently require only `chat:use`; revisit per-workspace read
      permissions for `GET /v1/chat/handoffs` when the dashboard defines queue access

## Reliability

- [~] Communication outbox: the email transport bridge consumes the queue
      (`scripts/run_messaging.py`; SMTP send + IMAP poll, dispatch evidence and captured
      replies surfaced in the communication panel) and WhatsApp runs in manual-link mode.
      Meta Cloud transport, delivery/webhook status sync, and automatic retry scheduling
      still to come
- [x] Messaging is sandboxed in Compose by default. It shipped the other way round, and a test
      asserted the live value under a name claiming the opposite — an operator following the docs
      and pointing SMTP at a real relay would have started sending candidate email from a stack they
      believed was sandboxed
- [ ] Retry/backoff policy audit per provider (failed sends stay queued and retry on the
      next run); circuit breakers for flaky integrations
- [ ] `send_attempts` is written on every dispatch and read by nothing; no cap, no backoff, no alert
- [x] `/readyz` endpoint (DB + messaging + audit + **queue** + **skills** checks, 503 when degraded),
      distinct from `/healthz`; security headers, body-size ceiling, and per-principal rate limits in
      `api/hardening.py`
- [ ] Graceful shutdown: drain in-flight pipeline runs on SIGTERM. Compose `stop` signals `sh`, which
      does not forward to the Python child in a `sh -c 'while true'` loop
- [x] Backup/restore drill documented and scripted (`scripts/backup.py --verify` restores into a
      scratch database and re-verifies the audit chain; runbook in `docs/deployment.md`). The image
      now installs `postgresql-client` so the documented command actually runs, and `/app/data/backups`
      is a volume
- [x] Audit chain verification scheduled: the `audit-verify` scheduler job runs from the compose
      `scheduler` service; an automated after-restore check is available via `backup.py --verify`

## Beauty / UX

- [ ] Chat: progressive token streaming + tool-call visibility (agent, tools read, citations) once
      the backend emits event-by-event SSE; today the client uses `POST /v1/chat` for status codes
- [ ] Communication panel: pre-queue preview endpoint for rejection messages (today the composed
      body is reviewed after queueing and before dispatch — nothing can be sent unreviewed)
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
