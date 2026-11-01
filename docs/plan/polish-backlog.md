# Polish Backlog — deferred optimization work

**Purpose:** everything we deliberately defer while widening must land here, or it is lost.
This is the worklist for the final hardening phase (performance, security, beauty, reliability,
docs). Nothing here is a feature — if it is missing functionality, it belongs in
`remaining-work.md` instead.

**Status:** active · created 2026-09-12 · entries are added the moment a deferral is made.

Legend: `[ ]` open · `[~]` partially addressed · `[x]` done.

## Performance

- [x] Database: index review per hot query. Every named case is covered: approvals
      (`assignee_role,status`; `subject,subject_id`; `sla_deadline`), tasks (`status,due_on`;
      `assignee_role,status`; `related_subject,related_id`), communications
      (`status,created_at`; normalized provider message id), the approval-sync queue
      (`consumed_at,created_at`), evaluations (`application_id`; `candidate_id,job_id`;
      `recommendation`), applications (`job_id,priority_score`; `candidate_id`), and audit
      (`subject_type,subject_id`; `created_at`; `seq` is the primary key). A live `EXPLAIN`
      pass on production-sized data is the remaining verification, not missing indexes.
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
- [x] Cache policy: evaluated and deliberately not added. Provider health checks are local
      config validation (no network), the skill fingerprint is a small deterministic hash with
      no hot caller, and rate tables must never serve a cached statutory value while an
      operator is correcting one. There is no measured hot path to justify the staleness risk;
      revisit only with a profile that names one.
- [ ] pgvector: HNSW/IVFFlat index parameters tuned against real corpus sizes — **blocked on a
      production-sized corpus**; tuning against synthetic vectors would encode a guess into a
      schema. The default index is correct, just not optimal for a scale we have not measured.
- [x] Web bundle: route-level code splitting shipped (workspace, application detail, import,
      jobs and operations load on demand; entry 891 KB → 425 KB, TBT 190 ms → 60 ms in the
      Lighthouse mobile run). A gzip budget now gates CI: `npm run size` fails over 180 KB for
      the entry chunk, 50 KB CSS or 400 KB total (`web/scripts/check-bundle-size.mjs`). The
      current build is 145/29/319 KB. Lighthouse itself is not in CI; the bundle budget is the
      regression gate chosen, because it catches the accidental-import failure mode cheaply.
- [x] Ingest path: extraction is bounded (200k characters, 200 PDF pages) and a cut-short
      document says so -- the flag travels on the queue message and the evaluation raises
      `document_truncated`, which routes the candidate to a person instead of scoring the part
      that was read. The streaming hash was not needed: the body ceiling already bounds the
      upload at 10 MiB and the bytes are in memory for storage.

## Observability

- [x] `/metrics` in Prometheus text format (`curl` is enough, no exporter stack), with the two
      canaries that would have caught the missing worker on day one:
      `hragents_applications_stuck_queued` and `hragents_scheduler_last_success_timestamp`
- [x] Scheduler and messaging loops write a JSON report to a shared volume every tick; `/metrics`
      reads it, so a job failing inside the scheduler loop goes stale instead of silent. Every loop
      container has a `HEALTHCHECK`
- [x] `/readyz` now checks `queue` and `skills` as well — it reports `degraded` when the product
      cannot work, not just when it cannot start
- [x] Request timing middleware with an `X-Response-Time-Ms` response header
- [x] Dead letters carry their reason: `QueueMessage.failed_reason` / `failed_at` are populated by
      all three backends, so an operator can see why a message died
- [~] Structured logging through the service layer: the pipeline's decision, the worker's
      per-message outcome, each scheduler job, approval creation/decisions, the retention sweep's
      summary and dead-letter requeues emit structured lines, and every request carries a
      correlation id that the logs inherit and the response echoes. The rest of the service layer
      is still silent
- [x] Request/correlation id bound to `structlog.contextvars` and echoed in responses
- [x] Dead-letter dashboard (`/app/ops`: metadata only, reason-gated requeue recorded
      on the audit chain) and the worker stuck-job reaper (`queue-reaper` scheduler job,
      leases expired beyond five minutes go back to pending with the attempt counted);
      the dead-letter alert ships in `ops/alerts/hragents.rules.yml`
- [x] OTel traces: the three unwired packages (`opentelemetry-sdk`,
      `opentelemetry-instrumentation-fastapi`, `opentelemetry-exporter-otlp-proto-http`) are out
      of the runtime dependencies, so the production image no longer carries them; the tracing
      itself stays open under Phase 9 observability
- [x] Cost tracking: tokens are recorded per evaluation/application, and the provider config
      carries operator-entered USD prices per million tokens (input, output, cache read). A
      price snapshot is stored on each ledger row, so a later price change cannot rewrite
      history. `GET /v1/ops/usage` aggregates by provider/model; `GET
      /v1/ops/usage/applications/{id}` and `GET /v1/ops/usage/candidates/{id}` roll up tokens,
      cost and the per-model split. An unpriced entry makes the rollup cost null with
      `uncosted_entries` set, never a partial sum that reads as the whole bill.
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
- [x] Shared rate limit for multi-replica deployments: `HRAGENTS_RATE_LIMIT_BACKEND=redis`
      moves the sliding window into one Redis sorted set per bucket, updated in a
      transaction so two processes cannot both take the last slot. The in-process
      limiter stays the default for the single-container install; an unreachable
      store fails open and logs, because the queue is down in that state too.
- [x] Body-size ceiling: the middleware counts bytes as they stream in, so a chunked upload
      is stopped mid-flight, and a declared length is refused without reading a byte; the
      document endpoint's own limit matches the middleware's
- [x] Key management: rotation procedure for API keys and provider credentials —
      `docs/deployment.md` §"Secrets and rotation" (prepend the new settings key, reload, revoke
      at the issuer; every rotation is audited) and the provider-credential settings key rotates
      through `services/sealing.py`'s Fernet key list
- [x] Upload scanning hook (ClamAV adapter) behind the storage provider — `services/scanning.py`
      records clean, refuses infected, and refuses a configured-but-unreachable scanner rather
      than storing unscanned. **Format validation** (`services/documents.py`) sniffs the bytes
      before scanning: PDF by `%PDF-`, DOCX only when the archive really contains
      `word/document.xml`, otherwise UTF-8 text; a suffix that disagrees with the bytes is
      refused, legacy `.doc`/`.xls`/`.ppt` are refused with guidance, and arbitrary binaries
      never reach a text parser. DOCX is now actually extracted from
      `word/document.xml` (bounded), matching the architecture's claim.
- [ ] Pen-test checklist executed against a staging instance; findings triaged here
- [x] **RLS actually applies in the shipped stack**: `docker/postgres/10-non-superuser.sql` demotes
      the image-created superuser on first init (ADR 0006 knew it was bypassed and deferred it).
      Existing volumes need the `ALTER ROLE` by hand
- [x] Log-redaction pass: every provider's declared `secret_fields` is checked to be a
      `SecretStr` (or `SecretStr | None`), and a Hypothesis fuzz asserts masking a nested
      payload never returns the raw secret for any printable value
      (`tests/providers/test_secret_hygiene.py`). A plain-`str` token can no longer be
      declared secret and leak through `mask_secrets`.
- [x] Dependency scanning cadence: Dependabot covers uv, GitHub Actions and npm weekly
      (`.github/dependabot.yml`), CodeQL runs in CI, and `.github/workflows/audit.yml` runs
      `pip-audit --strict` against the exported lockfile every Monday (plus manual dispatch).
      Its first run found and cleared advisories in `pypdf`, `joserfc` and `pyasn1`.
- [x] Session/auth hardening review: keys are compared with `secrets.compare_digest`, a managed
      install distinguishes `auth_required` from `auth_invalid` (401) and role refusal (403), the
      dashboard has a sign-in screen and keeps the key in `sessionStorage` (not `localStorage`),
      and the no-keys state is an explicit local-operator mode documented as localhost-only. The
      prior trap — keys configured but no login screen — no longer exists; both branches have UI
      and tests.
- [x] Handoff queue reads: listing `GET /v1/chat/handoffs` now requires `people:read`, not just
      `chat:use`. There is no per-principal workspace membership in the model, so scoping to
      "workspaces you belong to" cannot be expressed; the queue's free text can carry
      employee/candidate context, and an employee asking another team for help is still allowed
      to create one (`chat:use`). The read is an HR-operations view.

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
- [~] Retry/backoff policy audit per provider (failed sends stay queued and retry on the
      next run); circuit breakers for flaky integrations
- [~] `send_attempts` and `last_attempt_at` drive an exponential backoff (15 min, 30, 60 …
      capped at 24 h) so a bounced address is no longer retried on every scheduler tick;
      the message stays queued throughout and the outcome is reported as `deferred`, not
      failed. A dispatch lease (`claimed_by`/`claimed_until`, migration `0037`) stops two
      overlapping runs from sending the same message; an expired lease after a crash is
      claimable again (at-least-once). Still open: no alert on repeated failures, and no
      circuit breaker per provider
- [x] `/readyz` endpoint (DB + messaging + audit + **queue** + **skills** checks, 503 when degraded),
      distinct from `/healthz`; security headers, body-size ceiling, and per-principal rate limits in
      `api/hardening.py`
- [x] Graceful shutdown: the worker drains its in-flight batch on SIGTERM, and the
      scheduler/messaging loops run in Python (`--loop`, `services/periodic.py`) instead of
      `sh -c 'while true'`, so the signal reaches the process and the running tick finishes.
      Compose gives each a `stop_grace_period` longer than its work (worker 6m vs the 300s
      lease, scheduler 5m, messaging 2m); the old shell loop never forwarded SIGTERM to the
      Python child.
- [x] Backup/restore drill documented and scripted (`scripts/backup.py --verify` restores into a
      scratch database and re-verifies the audit chain; runbook in `docs/deployment.md`). The image
      now installs `postgresql-client` so the documented command actually runs, and `/app/data/backups`
      is a volume
- [x] Audit chain verification scheduled: the `audit-verify` scheduler job runs from the compose
      `scheduler` service; an automated after-restore check is available via `backup.py --verify`
- [~] Half-state repair: **the approval pair is transactional now.** `ApprovalEngine`
      writes the decided approval and its `pending_approval_syncs` row in one Postgres
      transaction (migration `0039`), and `approval-reconcile` consumes the row
      idempotently (domain refusal = already settled; store failure retried up to five
      attempts; then `gave_up` with the last error). Open: the same treatment for the
      other linked pairs (offers, scheduling, erasure) and a unit of work spanning
      arbitrary services

## Beauty / UX

- [x] Chat: progressive token streaming + tool-call visibility (agent, tools read, citations) —
      `PolicyAssistant.ask_stream` reports growth of the structured answer, `/v1/chat/stream`
      emits `delta` events before the final `reply`, and the client renders them into one
      placeholder that the grounded answer replaces. Only append-only growth is emitted,
      because a structured stream can revise a partial object; the final reply is
      authoritative. Tool usage ships on the same reply (`tools_used`)
- [x] Communication panel: pre-queue preview endpoint for rejection messages —
      `POST /v1/candidates/{id}/communications/rejection/preview` returns the exact
      subject/body and the blockers without storing anything, and the panel refuses to
      queue until that preview has been read (re-previewing when a field changes)
- [~] Motion pass: reduced-motion is global (`styles/globals.css` collapses animation and
      transition duration for `prefers-reduced-motion: reduce`) and skeleton loaders cover
      the workspaces that fetch (57 uses). Still open: optimistic updates where a local
      mutation is safe to show before the server confirms it.
- [x] Empty states, error states, and offline states: every workspace component renders
      `EmptyState` (2–9 uses each: records, approvals, leave, offboarding, payroll, growth,
      compliance), API failures render named/retryable errors (52 components handle `isError`),
      and the shell renders a global offline notice driven by the browser's `online`/`offline`
      events, with an icon plus a full-sentence label so it is never color-only.
- [~] Accessibility audit (axe + screen-reader pass): `axe-core` structural audits now run on the
      home, application-detail and operations pages and pass (color-contrast is disabled under
      jsdom and covered instead by `theme.contrast.test.ts`); the manual keyboard and WCAG AA
      contrast pass is done (2026-10, light+dark, all boards + palette). Remaining: add the same axe
      assertion to each workspace as its component test harness grows, and a screen-reader pass.
- [ ] EN/ID microcopy review with a native HR speaker; date/number/currency formatting audit
- [~] Design token audit against `product-concept.md` §7: colors are structurally guarded
      (`theme.guard.test.ts` confines every hex literal to `theme.css`; the contrast test pins
      WCAG AA in light and dark). A spacing pass found no off-scale large padding/margin; the
      only arbitrary value is shadcn's `p-[3px]` tabs inset, and the half-steps (`0.5`/`1.5`/
      `2.5` = 2/6/10px) are Tailwind density primitives. Enforcing the 4px scale as a hard guard
      would mean rewriting upstream component micro-spacing for no visible gain, so the audit is
      recorded rather than codified.

## Docs & developer experience

- [x] Docs site (mkdocs-material + Pages) with versioned API reference — `mkdocs.yml`,
      `.github/workflows/docs.yml` deploys `dev` on main and a tagged version with `mike`,
      old versions stay addressable
- [x] Postgres adapters for `ConversationStore` and `WorkspaceRequestStore` —
      `DbConversationStore` / `DbWorkspaceRequestStore` in `db/workspace.py` persist both
      through the configured session factory, so queues survive a restart
- [x] Operator runbooks: provider failures (`runbooks/provider-failure.md`), incident
      response (`runbooks/incident-response.md`) and upgrade/rollback
      (`runbooks/upgrade.md`), linked from the docs nav. They name the commands and the
      evidence to check rather than restating the deployment guide.
- [x] Reproduce benchmarks from a clean clone (script + CI artifact) —
      `scripts/benchmark_ingestion.py --json` prints one machine-readable object, and
      `.github/workflows/benchmark.yml` runs it weekly on a clean checkout and uploads
      `ingestion-benchmark` (30-day retention). The measured table stays in
      `docs/architecture/benchmarks.md`, with the CI caveat that runner hardware varies.
- [x] Type strictness evaluated: `mypy --strict src/hr_agents` reports 72 errors in 43 files —
      57 `no-any-return` (mostly `getattr(request.app.state, ...)`), 8 `attr-defined`,
      6 `type-arg`, 1 `redundant-cast`. Not adopted: the current flags already reject untyped
      defs and implicit optionals, and strict would mostly add casts around dynamic app state.
      Revisit when `AppState` is typed; the exact list is reproducible with the command above.
- [x] Branch coverage 100% on the invariant modules: scoring, policy, priority, audit and
      payroll are all at 100% lines and branches. `scripts/check_invariant_coverage.py`
      reads the JSON report and fails the gate (and CI) if any of the five loses a branch,
      so the global 90% floor cannot hide a regression in the code that decides money and
      truth.
- [x] Web: Storybook 10 for the component kit. `npm run storybook` runs the catalog and
      `npm run build-storybook` builds it; CI builds it after the app bundle. The first story is
      `Status/StatusBadge` (waiting/error/done). The config drops the app's PWA plugin, whose
      service-worker generation targets the app entry and fails on a catalog build. Output is
      gitignored and excluded from lint/format scans.

## Deferred by design (do not re-litigate without demand)

- [~] Live provider adapters: email (SMTP send + IMAP poll + Gmail API send), WhatsApp Cloud
      **sending and inbound**, Telegram Bot **send, channel dispatch and inbound**, and Google
      Calendar free/busy **feeding the interviewer directory** are live and tested over
      respx/MockTransport. Remaining, and **credential-blocked for live verification**:
      Google Drive/Sheets (needs its own OAuth scopes and file-picker flows) and Microsoft
      Graph (needs an Azure app registration and the client-credentials grant). Not
      credential-blocked but still open: calendar invites/reschedules are manual.
- [-] Managed cloud SaaS + billing
- [-] Office Connector folder-sync agent
