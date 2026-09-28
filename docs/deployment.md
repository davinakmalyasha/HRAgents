# Deployment & operations

How to run HRAgents on your own machine or a small server, and what to do when
something breaks. Everything here assumes the self-host path: Docker Compose,
PostgreSQL (with pgvector), Redis, MinIO, and Mailpit for local mail. No cloud
keys are required — the offline `test` model, hash embeddings, and manual
transports are the defaults.

## 1. One command

```bash
docker compose up --build
```

What starts:

| Service | What it does | Notes |
|---|---|---|
| `postgres` | pgvector database | volume `pgdata`, health-checked |
| `redis` | queue backend | volume `redisdata` |
| `minio` | document storage | volume `miniodata`, console on `:9001` |
| `mailpit` | local mail server | SMTP `1025`, inbox UI `http://localhost:8025` |
| `migrate` | `alembic upgrade head` | runs to completion, then the API starts |
| `api` | FastAPI + dashboard at `/app` | `http://localhost:8000/app`, health on `/healthz` and `/readyz` |
| `scheduler` | `scripts/run_scheduler.py --purge` every 15 min | the department clock |
| `messaging` | `scripts/run_messaging.py` every 5 min | carries the outbox, polls replies |

First start takes a few minutes (dashboard build). Watch progress with
`docker compose logs -f api`.

### Secrets

The committed defaults are for a laptop, not for a server. Before exposing the
instance, set real values in a `.env` file next to `docker-compose.yml`
(Compose reads it automatically):

```bash
HRAGENTS_API_KEYS=["a-long-random-string"]        # inbound API keys (empty = auth disabled)
# HRAGENTS_API_PRINCIPALS=[{"key":"...","role":"hr_admin","actor_id":"owner"}]
POSTGRES_PASSWORD=<strong password>
MINIO_ROOT_PASSWORD=<strong password>
HRAGENTS_MESSAGING_SANDBOX=false                  # only after you configure a real provider
```

Never commit `.env`; `.dockerignore` keeps it out of the image.

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
curl -s localhost:8000/healthz   # liveness: the process is up
curl -s localhost:8000/readyz    # readiness: database, messaging, audit sink
docker compose logs -f scheduler messaging
```

`/readyz` returns `503` with a per-dependency breakdown when something the API
needs is unreachable, which is what an orchestrator should probe.

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
