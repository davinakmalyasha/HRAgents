# Runbook: upgrade

Migrations are forward-only. The safe rollback is a database restore plus the
previous image, not `alembic downgrade` on production data.

## 1. Back up and prove the backup

```bash
docker compose exec api python scripts/backup.py --output /app/data/backups --verify
```

`--verify` restores the dump into a scratch database and checks the audit hash
chain inside it. A dump that has never been restored is not a backup. Keep the
file until the upgrade has been observed for a full scheduler cycle.

## 2. Read the release notes

Check `docs/plan/release-process.md` and the release's migration revisions.
Anything that changes a provider config shape or an environment variable is
called out there; the Settings UI keeps a stored secret when a field is left
blank, so a schema rename is the failure mode to look for.

## 3. Deploy

```bash
docker compose pull
docker compose up -d
```

The `migrate` service runs `alembic upgrade head` before the API starts; the
worker, scheduler and messaging services wait for it to complete successfully.
The scheduler and messaging loops run in Python now, so Compose's
`stop_grace_period` lets a running sweep or messaging pass finish before the old
container exits.

## 4. Verify

```bash
curl -fsS localhost:8000/readyz
docker compose exec api python scripts/verify_audit.py
docker compose ps                      # healthchecks, not just "Up"
docker compose logs --since=10m scheduler | tail -20
```

- `/readyz` must be 200; `/metrics` should show a fresh
  `hragents_scheduler_last_success_timestamp` within one interval (15 minutes).
- The ops page should show the same provider selections, with secrets still
  masked and a `…last4` preview rather than blank.
- Check `/v1/ops/usage` and `/v1/ops/dead-letters`; an upgrade that starts
  dead-lettering is not finished.
- If push notifications are configured, send one test notification; VAPID keys
  do not rotate on upgrade, but a changed subject does invalidate subscriptions.

## 5. Roll back

Only if the new version cannot serve:

1. Stop the stack.
2. Restore the dump taken in step 1 into the live database (`backup.py
   --restore <file>`), then re-verify the audit chain.
3. Deploy the previous image tag.
4. Confirm `/readyz` and the audit chain again.

A forward migration that already ran on data the old image cannot read is the
case this procedure exists for; do not try to reverse it in place.
