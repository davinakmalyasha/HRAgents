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
- [x] Pagination on every collection endpoint: all 49 list routes answer the `Page[T]`
      envelope, and every list that grows with the business now runs its predicate, ORDER BY,
      LIMIT/OFFSET and count in SQL rather than `select(Table)` plus a Python `sorted`
- [~] Home attention lists: the home reads one page (50 items) per queue instead of walking
      every page of three queues on every load, and it says what it did not show ("Showing 50
      of 143 approvals") with a link to the queue for the rest. Long-list virtualization is
      not needed at that size.
- [x] Manual pipeline stage transitions on the board: designed transition policy first
      (`docs/architecture/board-transitions.md`), then dnd-kit drag with keyboard support
- [x] Home: role-scoped 403s are named ("Not available for your role") instead of rendering
      as empty queues, and any other failure shows a retryable alert; "nothing needs you" only
      appears when all three queues answered.
- [x] N+1 audit of DB adapters once Postgres persistence lands (eager loading for timelines)
- [x] **LLM latency: the k extraction runs now execute concurrently** (`asyncio.gather`) instead of
      sequentially — k runs were k× the wall clock for no added signal
- [ ] Cache policy: skill registry fingerprint, rate tables, provider health (TTL + invalidation)
- [ ] pgvector: HNSW/IVFFlat index parameters tuned against real corpus sizes
- [~] Web bundle: route-level code splitting shipped (workspace, application detail, import,
      jobs and operations load on demand; entry 891 KB → 425 KB, TBT 190 ms → 60 ms in the
      Lighthouse mobile run). Icon tree-shaking is already implicit in the named lucide imports;
      a CI bundle/Lighthouse budget is the remaining piece.
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
- [x] Dead-letter dashboard (`/app/ops`: metadata only, reason-gated requeue recorded
      on the audit chain) and the worker stuck-job reaper (`queue-reaper` scheduler job,
      leases expired beyond five minutes go back to pending with the attempt counted);
      the dead-letter alert ships in `ops/alerts/hragents.rules.yml`
- [x] OTel traces: the three unwired packages (`opentelemetry-sdk`,
      `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp-proto-http`) are out
      of the runtime dependencies, so the production image no longer carries them; the tracing
      itself stays open under Phase 9 observability
- [ ] Cost tracking: no `usage()` call exists anywhere, so "what did this candidate cost" is
      unanswerable
- [x] Dependency and setting hygiene: `lizard` is used (`services/ast_analysis.py`, with
      `radon` for Python), so it stays; `tenacity` and `orjson` were never imported and are
      gone; `Settings.github_token`, `crossref_mailto`, `telegram_bot_token` and the two
      WhatsApp credentials were read by nobody and have been removed, and
      `tests/test_env_example.py` now fails if `.env.example` advertises a setting that does
      not exist

## Security maximization

- [x] Rate limits on public surfaces: the authentication middleware resolves the principal
      before the limiter runs, so the bucket is per principal; otherwise it is per client
      address, and `X-Forwarded-For` is honoured only behind an explicit
      `HRAGENTS_TRUST_PROXY_HEADERS=true`
- [x] Rate-limiter key eviction: the bucket table is bounded by `max_tracked_keys`, expired
      buckets are pruned first, and what goes next is the least recently used -- never the
      principal being checked, whose window a refusal must not reset
- [x] Body-size ceiling: the middleware counts bytes as they stream in, so a chunked upload
      is stopped mid-flight, and a declared length is refused without reading a byte; the
      document endpoint's own limit matches the middleware's
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
- [ ] Accessibility audit (axe + screen-reader pass) on all workspaces — the manual keyboard and
      WCAG AA contrast pass is done (2026-10, light+dark, all boards + palette), see
      `theme.contrast.test.ts`
- [ ] EN/ID microcopy review with a native HR speaker; date/number/currency formatting audit
- [ ] Design token audit against `product-concept.md` §7 (no rogue colors/spacing)

## Docs & developer experience

- [ ] Docs site (mkdocs-material + Pages) with versioned API reference
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
