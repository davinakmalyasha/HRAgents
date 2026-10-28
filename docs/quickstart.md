# Quickstart

Docker Desktop, five minutes, no cloud keys.

## 1. Configure

```bash
git clone https://github.com/davinakmalyasha/HRAgents
cd HRAgents
uv run python scripts/setup.py
```

`scripts/setup.py` writes `.env` (gitignored) with the operator's name, one
role-bound admin key, the business timezone and the offline model default. It
prints the key once. No `uv` on the host? Copy `.env.example` to `.env` and set
the same values by hand.

## 2. Start

```bash
docker compose up --build -d
```

Nine containers come up: Postgres (pgvector), Redis, MinIO, Mailpit, a one-shot
migration, the API, the evaluation worker, the scheduler and the messaging
bridge. Migrations run before the API serves.

Prefer the published image over a local build?

```bash
HRAGENTS_IMAGE=ghcr.io/davinakmalyasha/hragents:0.15.2 docker compose pull
HRAGENTS_IMAGE=ghcr.io/davinakmalyasha/hragents:0.15.2 docker compose up -d --no-build
```

## 3. Sign in

Open **<http://localhost:8000/app>** and paste the key from step 1.

The first-run card offers starter checklists and the empty statutory-table
shells. Want something to look at instead?

```bash
docker compose exec api uv run python scripts/seed_demo.py
```

The demo seeds five employees, a hiring pipeline, a pending leave approval and a
payroll run — through the real services, so the audit trail and queues are
populated. The statutory rate tables arrive **unverified on purpose**: payroll
refuses to compute until a named human enters and verifies the numbers against a
real source.

## 4. Check it is actually working

```bash
curl -s localhost:8000/readyz | python -m json.tool   # queue + skills must be "ok"
curl -s localhost:8000/metrics | grep stuck_queued   # non-zero = the worker is down
```

The worker is not optional: the API accepts and publishes an application, and
only the worker evaluates it. Without it, submissions sit in `queued` forever
and everything looks fine.

## Next

- [Deployment & operations](deployment.md) — backups, upgrades, runbooks,
  provider configuration, offline mode.
- [Architecture](architecture/system-architecture.md) — the pipeline and the
  nine departments.
- [Human-in-the-loop bounds](architecture/hitl-bounds.md) — what runs
  automatically and what never will.
