# Runbook: provider failure

Provider health badges validate configuration; they do not prove the upstream
is reachable. "Badge ok, requests failing" is a network/credential problem, not
a configuration-schema problem. Start with `/app/ops` → Connections and the API
logs (`docker compose logs -f api worker scheduler messaging`).

## A model provider fails

1. `GET /readyz` reports the queue and provider readiness; `/metrics` exposes
   `hragents_scheduler_last_success_timestamp` and queue depth.
2. The worker retries a message up to `--max-attempts` (default 3), then
   dead-letters it. Read `GET /v1/ops/dead-letters`; the reason is on each row.
3. Fix the credential in Connections (or `.env` if the capability is locked),
   restart the worker, then requeue with
   `POST /v1/ops/dead-letters/{id}/requeue` and a mandatory reason.
4. The deterministic core keeps working while extraction is down: scoring,
   policy, payroll arithmetic and approvals never call a model.

If the provider is rate-limited, lower `HRAGENTS_SCORING_RUNS` (k) rather than
raising concurrency; k independent extractions multiply both cost and load.

## A queued message is not being sent

`GET /v1/candidates/{id}/communications` shows `send_attempts`, `last_error`
and `last_attempt_at` per row.

- **No recipient** — the row is skipped with `no ... on file`; queue it again
  with the address, or record dispatch manually.
- **Backoff** — a failed attempt defers the next for an increasing interval.
  Do not clear `last_attempt_at` by hand; wait, or fix the transport and let
  the dispatcher retry.
- **Lease held** — a crashed dispatcher keeps the lease until it expires
  (ten minutes). The next pass retries; `queue-reaper` handles the work queue,
  not the communication outbox.
- **Sandbox** — `HRAGENTS_MESSAGING_SANDBOX=true` leaves everything queued by
  design. Set it to `false` on the messaging service only.

Email: `uv run python scripts/run_messaging.py --send`
WhatsApp: `--whatsapp` · Telegram: `--telegram`

## Provider health says `misconfigured` / `degraded`

`degraded` is deliberate honesty, not a bug: WhatsApp send works without
`app_secret` but inbound does not; Telegram send works without
`webhook_secret` but inbound does not; Gmail send needs the refresh token.
Fix the named field in Connections and restart the service that built the
provider (API, worker, scheduler, messaging).

## Calendar sync fails for one interviewer

`calendar-sync` counts the failure and leaves that interviewer's existing slots
untouched rather than wiping them. Check the Google Calendar provider config and
that the interviewer's `calendar_id` is shared with the service account or
refresh-token identity. `GET /v1/scheduling/availability/{id}/calendar` shows
the mapping; `PUT` replaces it.

## Rotating a provider credential

Prefer the dashboard (sealed at rest). If the capability is locked, update the
environment secret and restart every service that uses it — the API, worker,
scheduler and messaging each hold their own provider object. Old credentials
remain valid at the issuer until you revoke them there; revoking is a separate,
manual step.
