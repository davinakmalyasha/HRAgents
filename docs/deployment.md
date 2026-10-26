# Deployment & operations

How to run HRAgents on your own machine or a small server, and what to do when
something breaks. Everything here assumes the self-host path: Docker Compose,
PostgreSQL (with pgvector), Redis, MinIO, and Mailpit for local mail. No cloud
keys are required — the offline `test` model, hash embeddings, and manual
transports are the defaults.

## 1. One command

Generate the local configuration first — the operator's name, a role-bound admin
key, the business timezone, and the offline model default:

```bash
uv run python scripts/setup.py
```

It writes `.env` (never committed) with one `hr_admin` principal. Compose loads
that file through `env_file`; the stack's fixed wiring still wins where it
matters. The key is printed once — paste it into the dashboard sign-in. Without
`uv` on the host, copy `.env.example` to `.env` and set the same values by hand.

Then:

```bash
docker compose up --build
```

To run the published release instead of building it, select a tag and skip the
build:

```bash
HRAGENTS_IMAGE=ghcr.io/davinakmalyasha/hragents:0.1.0 docker compose pull
HRAGENTS_IMAGE=ghcr.io/davinakmalyasha/hragents:0.1.0 docker compose up -d --no-build
```

Images are multi-arch (`linux/amd64` and `linux/arm64`). Each release publishes
the exact version, its `major.minor`, `latest`, and a `sha-…` tag. The release
workflow fails on CRITICAL vulnerabilities it can fix, and attaches the Trivy
SARIF and an SPDX SBOM to the release; the SBOM and max-mode provenance are
also attached to the image digest in the registry.

What starts:

| Service | What it does | Notes |
|---|---|---|
| `postgres` | database | volume `pgdata`, health-checked, RLS enforced (see below) |
| `redis` | queue backend | volume `redisdata` |
| `minio` | object storage (reserved) | volume `miniodata`, console on `:9001`; documents still live in Postgres |
| `mailpit` | local mail server | SMTP `1025`, inbox UI `http://localhost:8025` |
| `migrate` | `alembic upgrade head` | runs to completion, then the API starts |
| `api` | FastAPI + dashboard at `/app` | `http://localhost:8000/app`, health on `/healthz` and `/readyz` |
| `worker` | `scripts/run_worker.py` | **the pipeline**: claims queued applications and evaluates them |
| `scheduler` | `scripts/run_scheduler.py --purge` every 15 min | the department clock |
| `messaging` | `scripts/run_messaging.py` every 5 min | carries the outbox, polls replies |

First start takes a few minutes (dashboard build). Watch progress with
`docker compose logs -f api worker`.

> **The worker is not optional.** The API accepts an application and publishes it;
> only the worker evaluates it. Without it, submissions sit in `queued` forever
> and everything looks like it worked. Check
> `curl -s localhost:8000/metrics | grep stuck_queued` — a non-zero value means
> nothing is draining the queue.

> **Row-level security.** The Postgres image creates the database owner as a
> superuser, and a superuser bypasses every RLS policy. `docker/postgres/` runs
> once on first init to demote it (`NOSUPERUSER NOBYPASSRLS`). The policies on all
> 35 tables are otherwise decorative in the shipped stack. If you are upgrading an
> existing volume, run `ALTER ROLE hragents NOSUPERUSER NOCREATEROLE NOBYPASSRLS;`
> by hand.

### What is wired

`GET /v1/providers` (admin key) reports, for every capability, the provider in use, whether
the environment locks it, and what that provider's own health check says. Configuration comes
back masked — the last four characters of a secret, never the secret. The same list is on the
operations page (`/app/ops`).

### Editing providers

The operations page (`/app/ops`) can change a capability's provider and its
configuration once the operator supplies an encryption key. Without one the
panel stays read-only — a credential will not be stored in the clear.

```bash
uv run python scripts/settings_key.py
```

Put the printed line in `.env` and restart. The key seals every config before
it is written; responses show only the last four characters of a secret, and a
blank secret on update keeps the stored value. A stored selection wins over
`.env` unless the environment locks the capability
(`HRAGENTS_PROVIDER_<CAPABILITY>_LOCK=true`); the compose stack locks the queue.
Services built at startup — the model runtime, the queue — take a change after
a restart, which the response says.

To rotate the key, prepend the new key to the comma-separated list, restart,
re-save the providers you changed (the UI keeps the secret when the field is
blank), then remove the old key.

### Verified credentials

A certificate on a CV is a claim. The credential registry is where an operator
records what the issuer actually confirmed, and scoring only trusts it once a
named human has verified the registry with a source.

```bash
curl -s -X POST localhost:8000/v1/credentials -H "X-API-Key: $KEY"   -d '{"name":"AWS certifications","issuer":"AWS"}'
# add the rows you checked, then certify them
curl -s -X PUT localhost:8000/v1/credentials/$ID/entries -H "X-API-Key: $KEY"   -d '{"entries":[{"name":"AWS Solutions Architect","expires_on":"2027-01-01"}]}'
curl -s -X POST localhost:8000/v1/credentials/$ID/verify -H "X-API-Key: $KEY"   -d '{"source_note":"issuer page, 2026-10-24"}'
```

A registry is inert until verified. Once at least one is usable, a claim that
matches nothing counts as **unverified** (a Coursera badge and a genuine
certificate stop scoring alike), while an entry past `expires_on` answers
expired. Editing entries invalidates the verification, exactly like a rate
table. The compliance queue has the same import path in the dashboard: create a
registry, paste its rows (one per line, `name | status | id | expiry | notes`),
then verify it with the source you checked.

### Malware scanning

Uploads are stored unscanned by default, and the audit entry says so. Point the
API at a ClamAV daemon to scan before storage:

```bash
HRAGENTS_CLAMAV_HOST=clamav      # or localhost, a sidecar, a socket proxy
HRAGENTS_CLAMAV_PORT=3310
HRAGENTS_CLAMAV_TIMEOUT=5
```

- **clean** → stored; the `document.uploaded` entry records `scan=clean`.
- **infected** → refused with `422`; nothing is stored, and
  `document.rejected_malware` records the signature — never the file or its name.
- **scanner unreachable** → refused with `503`; the file is *not* stored. A
  configured scanner that is down must not silently downgrade to unscanned.

The scan speaks ClamAV's INSTREAM protocol over TCP, with no shell and a bounded
timeout. The hook lives in `DocumentService.upload`, the one path that accepts
arbitrary bytes; an employee-document row registered against an existing object
does not bypass it because it carries no content.

### External MCP tools (optional, HTTP/SSE only)

An operator can attach an MCP server for tools that live outside HRAgents
(an ATS or HRIS connector). Two limits are deliberate:

- **No stdio transport.** A stdio server would mean spawning a process; the
  product's rule is that agents never get a shell, so only HTTP/SSE endpoints
  are accepted.
- **Destructive tools are not exposed.** The registry's human-approval gate needs
  a dry-run preview, and an MCP tool cannot produce one without making the call.
  Read and write tools can be exposed; destructive actions stay in the product,
  where a named human approves a preview.

Configuration is one JSON value:

```bash
HRAGENTS_MCP_SERVERS='[
  {"name":"ats","url":"https://mcp.example.com/mcp","auth_env":"ATS_MCP_TOKEN",
   "allowed_agents":["screening_coordinator"],
   "tools":{"get_candidate":"read","add_note":"write"}}
]'
```

Only the tools named under `tools` are registered (`mcp.<server>.<tool>`); a
tool the server adds later stays invisible until the operator names it.
`allowed_agents` is the other half of least privilege — an empty list connects
the server for discovery but exposes nothing. The bearer token is read from the
variable named by `auth_env`, never from the URL, config or logs; putting
credentials in the URL is refused.

A server that is unreachable or unauthenticated degrades only itself: the app
starts, the other tools work, and `GET /v1/ops/mcp` (admin) lists each server's
connection state and exposed tools. The Settings → Connections form is not built
yet; this is an environment-configured surface.

### Secrets and rotation

Nothing in this repository ships a secret. Rotate after any suspicion, and in
this order so a rotation cannot lock you out:

**API keys and principals.** Add the new key to `HRAGENTS_API_PRINCIPALS` (keep
the old one), restart, move clients, then remove the old entry and restart. A
removed key answers 401 on the next request and the dashboard drops it. The
audit chain records the actor id, so rotating a key for the same person keeps the
same name on the record. An unbound `HRAGENTS_API_KEYS` key is one shared
identity; prefer principals.

**Settings encryption key** (provider credentials). Prepend a new key to the
comma-separated `HRAGENTS_SETTINGS_ENCRYPTION_KEY`, restart, re-save the
providers you changed (a blank secret keeps the stored value), then remove the
old key. Rows stay readable while both keys are present.

**VAPID (push).** Generate a new pair, put it in `.env`, restart. Existing
browser subscriptions were bound to the old application key and will not
deliver; each person must turn the bell off and on (which unsubscribes,
deletes the server row and re-subscribes with the new key).

**Provider credentials.** Prefer the dashboard (sealed at rest) — Save, then
Test. If the capability is environment-locked, update the env value and
restart. Revoke the old credential at the provider only after the Test button
answers.

**Database, MinIO, SMTP/IMAP.** Change the password on the service, update
`.env`/compose, restart, then confirm `/readyz`. Backups taken before the change
remain restorable with the old credentials; they do not contain the new one.

**After every rotation**, revoke the old secret at its issuer. The audit chain
stores actor ids and field names, never the secret value, so it does not need
rewriting.

### Data governance

Full export, deletion, subprocessors and the DPA template are in [Data governance](data-governance.md).

### Push notifications (optional)

Notifications stay off until the operator issues a VAPID pair **for this
deployment**. No key is shipped: a committed private key would let anyone
impersonate the sender for every install.

```bash
uv run python scripts/vapid_keys.py
```

Copy the three printed lines into `.env` and restart. The private key stays on
the server; `GET /v1/push/config` serves only the public half. With keys
configured the topbar shows a bell: turning it on subscribes this browser and
sends one test notification, so "on" is a demonstrated fact rather than a
promise.

New approvals are announced to the roles that may decide them. Payloads name
the subject ("a leave request needs your decision") and never the employee or
an amount: a lock screen is not an access-controlled surface. Delivery is
best-effort and runs outside the approval path, so an unreachable push service
cannot block the decision it was announcing. An endpoint the browser has
dropped (404/410) is pruned, and a person whose key is removed or whose role
changes stops receiving pings. Browsers require HTTPS for service workers;
`localhost` is the exception.

### Starter content

A fresh install is empty by design. The dashboard's first-run card offers the
same seed as the CLI:

```bash
docker compose exec api uv run python scripts/seed_starters.py
```

It creates an onboarding and an offboarding checklist and one **empty** shell per
statutory table kind payroll needs. No values are seeded: a named human enters and
verifies every number, and payroll refuses to compute until that happens.

### Demo data

To see the product with a story in it:

```bash
docker compose exec api uv run python scripts/seed_demo.py
```

Five employees (one mid-probation), two contracts, an expiring KTP, a pending
annual-leave approval, an open engineering role with two applications, an
onboarding plan, a draft growth cycle and a payroll run for the current month.
Everything is created through the real services, so the audit trail, the
approval queue, the task list and the retention ledger are populated too.
The marker employee number `DEMO-001` makes the seed idempotent on Postgres;
with the in-memory backend each process starts empty, so every run reseeds —
and a separately started dev server will not see a standalone seed, because
the two processes share no store. Use the Compose stack (Postgres) for a demo
you can browse.

The statutory rate tables are seeded **unverified** on purpose. Payroll refuses
to compute on a table nobody has checked against a source, and the demo should
show that gate rather than fake a figure: verify the tables with real statutory
sources before using any number.

### Secrets

The committed defaults are for a laptop, not for a server. Before exposing the
instance, set real values in a `.env` file next to `docker-compose.yml`
(Compose reads it automatically):

```bash
HRAGENTS_API_KEYS=["a-long-random-string"]        # inbound API keys (empty = auth disabled)
# HRAGENTS_API_PRINCIPALS=[{"key":"...","role":"hr_admin","actor_id":"owner"}]
HRAGENTS_TIMEZONE=Asia/Jakarta                    # the zone business dates are read in
POSTGRES_PASSWORD=<strong password>
MINIO_ROOT_PASSWORD=<strong password>
HRAGENTS_MESSAGING_SANDBOX=false                  # only after you configure a real provider
```

`HRAGENTS_TIMEZONE` decides what "today" means for leave years, probation ends,
due dates and the sweeps that act on them. It defaults to `Asia/Jakarta`, and an
unknown zone stops startup rather than silently falling back — a server whose
host clock is UTC would otherwise be a day off for the seven hours after Jakarta
has rolled over.

Never commit `.env`; `.dockerignore` keeps it out of the image.

### Binding a key to an employee

`role` decides what a principal may do across the whole org. `employee_id`
decides whose records they may act on individually, and the self-service routes
need it: an employee requesting their own leave, or moving their own goal along,
is refused without it. A key with no `employee_id` is not a weaker form of an
employee key, it is ineligible for those routes.

```bash
HRAGENTS_API_PRINCIPALS=[
  {"key":"...","role":"employee","actor_id":"sari","employee_id":"<uuid>"},
  {"key":"...","role":"manager","actor_id":"budi","employee_id":"<uuid>"}
]
```

Take the UUID from the employee record. A manager additionally needs
`employee_id` set to *their own* record, not their reports': the reporting line
comes from each employee's `manager_id`, so the manager's own binding is what
identifies them as the manager. `hr_admin` and `recruiter` hold `people:write`
and need no binding to act on any record.

Identity is bound by configuration rather than inferred from an email address,
because an email is a nullable, changeable, shareable field, and a permission
that depends on one is not a permission. An unbound principal is refused rather
than assumed to own whatever it names.

> **What the two modes mean.** With no keys configured, every request is accepted
> as a local development principal with full admin rights — appropriate for
> `localhost`, not for a server. With keys configured, the dashboard signs in:
> the first request it makes is `/v1/session`, and if the server refuses it the
> app shows a sign-in screen that takes the API key. The key is kept in
> `sessionStorage`, so closing the tab ends the session, and signing out clears
> it and the cache. The sign-in screen never decides anything itself: the role
> it displays is the one the server resolved, and every permission is still
> checked server-side.
>
> Still not a substitute for TLS. The key travels in an `X-API-Key` header and is
> readable by any script on the origin, so a self-host exposed to a network wants
> a reverse proxy that terminates TLS and restricts who can reach it. There are
> no passwords and therefore no password reset: the credential *is* the key, and
> rotating it means changing the configured principal.

## 2. Connecting a real mail provider

Compose ships Mailpit so nothing leaves your machine while you evaluate. To
send real email, point the provider layer at your mailbox and leave the sandbox
alone:

```bash
HRAGENTS_PROVIDER_EMAIL_SEND=email.smtp
HRAGENTS_PROVIDER_EMAIL_SEND_CONFIG={"host":"smtp.example.com","port":587,"username":"hr@example.com","password":"...","from_address":"hr@example.com"}
HRAGENTS_PROVIDER_EMAIL_RECEIVE=email.imap_poll
HRAGENTS_PROVIDER_EMAIL_RECEIVE_CONFIG={"host":"imap.example.com","username":"hr@example.com","password":"...","mailbox":"INBOX"}
```

Then `docker compose up -d --force-recreate api messaging`. Until a message is
queued behind a named human, nothing is sent — and the bridge records the
provider, the message id, and any failure on the message itself.

## 3. Health, logs, metrics

```bash
curl -s localhost:8000/healthz                    # liveness: the process is up
curl -s localhost:8000/readyz                     # readiness, per dependency
curl -s localhost:8000/metrics | grep stuck_queued # is anything draining the queue?
docker compose logs -f api worker scheduler messaging
```

`/readyz` returns `503` with a per-dependency breakdown when something is
unreachable, which is what an orchestrator should probe. It checks
`database`, `messaging`, `audit`, **`queue`**, and **`skills`** — the last two
because they decide whether the product *works* rather than whether it starts: no
queue means submissions are accepted and never evaluated, and no skills library
means every agent runs with no runbook.

`/metrics` is plain Prometheus text; `curl` is enough, no exporter stack. The
series worth alerting on:

| Series | Meaning |
|---|---|
| `hragents_applications_stuck_queued` | accepted but never evaluated — **the worker is down or wedged** |
| `hragents_scheduler_last_success_timestamp` | per job; a stale value means a job is failing inside the `while true` loop |
| `hragents_applications_by_status` | where the pipeline actually is |
| `hragents_http_request_duration_seconds_sum` | paired with `_count` for a mean |
| `hragents_queue_pending` / `_inflight` / `_dead` | evaluation queue depth per topic; `_dead` above zero is a message that exhausted its retries |

The `scheduler` and `messaging` loops swallow failures (`|| echo ...`) because a
crashing tick should not kill the container. They rewrite their JSON report on a
shared volume every tick, and the metrics endpoint reads it — that is how a
silently failing loop becomes visible without adding a log aggregator. The
containers also have `HEALTHCHECK`s, so `docker compose ps` shows the truth.

### Alerting

The repository ships Prometheus rules for the canaries and the usual API
signals: [`ops/alerts/hragents.rules.yml`](https://github.com/davinakmalyasha/HRAgents/blob/main/ops/alerts/hragents.rules.yml).
Scrape the API with a job named `hragents-api` and load the file as a rule
file; nothing else is required.

| Alert | Severity | What it means |
|---|---|---|
| `HRAgentsStuckQueuedApplications` | critical | submissions are accepted and nothing is evaluating them — start or restart the worker |
| `HRAgentsSchedulerJobStale` | critical | a scheduled job missed three 15-minute ticks; retention, expiry and offer expiry all live there |
| `HRAgentsDeadLetteredMessages` | warning | a message exhausted its retries; read its reason and requeue deliberately |
| `HRAgentsQueueBacklog` | warning | more than 100 messages waiting for half an hour |
| `HRAgentsApiDown` / `HRAgentsHighErrorRate` / `HRAgentsSlowResponses` | critical / warning | the ordinary API signals |

Nothing pages by itself: the rules are the operator's to load, and `/readyz`
remains the external probe for orchestrators. The rules test
(`tests/test_alerts_config.py`) fails if a rule references a series the API no
longer renders, so a renamed metric cannot silently disable an alert.

The dead letters themselves are readable at `GET /v1/ops/dead-letters`
(`admin:manage`; metadata and payload keys, never the résumé text) and a
requeue is `POST /v1/ops/dead-letters/{id}/requeue` with a mandatory reason,
recorded on the audit chain. Requeueing resets the attempt budget because a
person decided the cause is fixed; the automatic reaper does the opposite and
counts the attempt, so a crash-looping message still runs out of retries. The
`queue-reaper` scheduler job returns leases older than five minutes to pending,
which covers a worker wedged on the handler itself. The dashboard mirrors the
API at `/app/ops` (reachable from the command palette) with the same
reason-gated requeue.

## 4. Backups (and proving they work)

```bash
docker compose exec api python scripts/backup.py --output /app/data/backups --verify
```

`--verify` restores the dump into a throwaway database and re-verifies the audit
hash chain inside it. A backup you have not restored is a guess; this script
prints `audit chain: intact` or fails with the first broken sequence. Restore a
dump with:

```bash
docker compose exec api python scripts/backup.py --restore /app/data/backups/hragents-<stamp>.sql.gz
```

## 5. Upgrades

```bash
git pull
docker compose up --build -d          # runs migrations, restarts services
docker compose exec api python scripts/verify_audit.py     # chain still intact
```

Migrations are additive and reversible (`alembic downgrade -1`). Take a backup
first when a release contains a data migration.

## 6. Runbooks

**Candidate messages stuck in "queued".** Check the messaging logs. A failed
send keeps the message queued and records `last_error` on it (visible in the
communication panel). Fix the transport and the next run retries.

**The scheduler job failed.** `run_scheduler.py` prints one line per job and
exits nonzero on failure. Run a single job on demand:

```bash
docker compose exec api python scripts/run_scheduler.py --job retention --purge
docker compose exec api python scripts/run_scheduler.py --job reply-sla
```

**Audit chain verification fails.** `python scripts/verify_audit.py` prints the
first invalid sequence. That means a row in `audit_log` was altered out of
band: restore from backup and investigate the database access path. Never edit
`audit_log` by hand.

**LLM provider is not configured.** Agents fall back to the offline model, so
the deterministic core (scoring, policy, approvals) keeps working. Configure
`HRAGENTS_PROVIDER_LLM` to enable extraction.

**Rate limit (429).** The API throttles per principal at 300 requests/minute by
default. Raise `HRAGENTS_API_RATE_LIMIT_PER_MINUTE` or add a role-bound key.

## 7. Without Docker

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn hr_agents.main:app --reload     # API + dashboard on :8000
uv run python scripts/run_scheduler.py          # the clock, in another shell
uv run python scripts/run_messaging.py          # the messaging bridge
```

In-memory mode (`HRAGENTS_STORE_BACKEND=memory`, the default) needs nothing at
all: it is the zero-configuration developer experience and the right choice for
a demo, not for real HR data.

## 8. Fully offline (local models)

Everything below keeps candidate and employee data on the machine. The
deterministic core — scoring, payroll arithmetic, policy routing, approvals —
never calls a model in the first place, so what this section configures is
extraction, drafting and chat.

### Point every capability at something local

```bash
HRAGENTS_PROVIDER_LLM=llm.ollama
HRAGENTS_PROVIDER_LLM_CONFIG={"model":"qwen2.5:7b"}
HRAGENTS_PROVIDER_EMBEDDINGS=embeddings.ollama
HRAGENTS_PROVIDER_EMBEDDINGS_CONFIG={"model":"nomic-embed-text"}
HRAGENTS_PROVIDER_STORAGE=storage.local_disk
HRAGENTS_PROVIDER_STORAGE_CONFIG={"root":"data/documents"}
HRAGENTS_PROVIDER_QUEUE=queue.memory
HRAGENTS_PROVIDER_WHATSAPP=whatsapp.manual_links
HRAGENTS_PROVIDER_CALENDAR=calendar.manual_slots
```

`whatsapp.manual_links` and `calendar.manual_slots` need no credentials at all:
you send the message from your own WhatsApp and enter interview slots by hand,
and the app composes the link and the ICS. For email, point `email.smtp` and
`email.imap_poll` at the Mailpit container from §1 — it is a local mail server,
so nothing leaves the host.

### Get the models

```bash
ollama pull qwen2.5:7b          # extraction, drafting, chat
ollama pull nomic-embed-text    # embeddings, 768 dimensions
```

**Model floor.** Extraction asks a model to return structured data from a CV and
to keep two similar profiles straight. A 7–8B instruction-tuned model is the
floor at which that is reliable; 14B and up is visibly better on ambiguous
résumés and on the drafted summaries a person edits. Below the floor the failure
mode is quiet: fields come back plausible-but-wrong, which is worse than a
refusal, because nothing downstream can tell. If you have no model to run,
`embeddings.hash` implements embeddings with no download at all — it is lexical
overlap, not meaning, so it finds documents that share words and misses ones
that share sense.

### What the offline mode does not do

- GitHub and repository lookups, publication checks and credential registries
  need the network. Offline, those signals are simply absent from an
  evaluation, and the deterministic scorer treats absent evidence as absent
  rather than guessing.
- The built-in `test` model runs the whole pipeline with canned responses so
  tests and demos need neither a network nor a model. Its numbers are fake by
  construction; never use it for a real candidate.
- Provider health badges report *configured*, not *reachable*: the health probe
  is a Phase 7 item, so verify Ollama yourself with `ollama list` and one
  extraction from the dashboard before trusting a batch.
