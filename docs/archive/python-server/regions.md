# Region and network recipes

Two things vary by where the instance runs: **the business clock** and **how the
outside world reaches it**. Nothing else in HRAgents is region-specific by
design — statutory numbers are operator data, and providers are configuration.

## Jakarta (or anywhere in Indonesia)

```bash
HRAGENTS_TIMEZONE=Asia/Jakarta      # the default; set it explicitly anyway
```

- **Clock.** Leave years, probation ends, contract expiry and every retention
  sweep use the business day from this zone. A host whose clock is UTC is fine;
  what matters is the timezone setting, and an unknown zone refuses startup.
- **Data residency.** The whole stack is yours: Postgres, Redis, MinIO and the
  document bytes live on your host. Nothing leaves until you configure a
  hosted model, mail relay or object store. If your policy requires in-country
  processing, keep those providers in-country or use Ollama and Mailpit.
- **Latency.** Hosted models in Singapore add roughly 10–30 ms per request
  versus a local model; model latency dominates either way (the live eval
  average was ~82 s for an extraction with a hosted model). Bulk evaluation is
  asynchronous, so ping is not the bottleneck — the model is.
- **Backups.** Keep the `pg_dump` and MinIO snapshots in the same jurisdiction.
  The backup drill (`scripts/backup.py --verify`) does not care where they live,
  but your DPA might.
- **TLS.** Terminate HTTPS at a reverse proxy (Caddy, nginx) or a tunnel
  (below). Service workers and push notifications require a secure context, so
  the dashboard is not fully functional over plain HTTP except on localhost.

## Singapore

```bash
HRAGENTS_TIMEZONE=Asia/Singapore     # only if the business day is Singapore's
```

- **Do not change the timezone to match the server.** It is the *business* zone,
  not the host zone. Set it to where the company's HR calendar operates, even if
  the server is in Singapore and the office is in Jakarta.
- **Latency** to Indonesian users is small; the same notes as Jakarta apply.

## Cloudflare Tunnel (webhooks without a public IP)

Some integrations need a public HTTPS URL: inbound email webhooks, WhatsApp
Cloud, or a calendar push. A tunnel gives you one without opening a port.

1. Create a tunnel in the Cloudflare dashboard and note the token.
2. Run `cloudflared` next to the stack. In `docker-compose.yml`:

   ```yaml
   tunnel:
     image: cloudflare/cloudflared:latest
     command: tunnel --no-autoupdate run
     environment:
       TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
     depends_on:
       api:
         condition: service_started
     restart: unless-stopped
   ```

3. In the tunnel's public-hostname mapping, point your hostname at
   `http://api:8000`. The API already answers `GET /healthz` and `/readyz`; use
   one of them for the tunnel's own health check.
4. Set `HRAGENTS_TRUST_PROXY_HEADERS=true` on the API **only** when nothing can
   reach port 8000 except the tunnel. Without it, the rate limiter buckets every
   request under `cloudflared`'s address — one shared bucket for all users. With
   it and a directly reachable origin, a client can spoof the header and mint a
   fresh bucket.
5. Give the integration the public hostname. For email, that is the provider's
   inbound webhook; for WhatsApp Cloud, the callback URL plus the verify token
   you configured.
6. Keep the origin private: bind the API to the compose network (the shipped
   stack does) and do not publish 8000 as well.

**What the tunnel does not do.** It does not add authentication. The API's own
keys are the gate; do not put an unauthenticated admin surface behind a tunnel
just because the URL is long. If you terminate access at Cloudflare, keep the
API's authentication on as well — defence in depth, not either/or.

## Checklist for a new region

- [ ] `HRAGENTS_TIMEZONE` is the **business** zone, not the host's
- [ ] The database, object store and backups are in the jurisdiction you claim
- [ ] A hosted model/mail provider is allowed by your data policy, or Ollama and
      Mailpit are used
- [ ] HTTPS terminates at a proxy or tunnel; `/readyz` is monitored from outside
- [ ] `HRAGENTS_VAPID_SUBJECT` names an address you control (push)
- [ ] The backup drill has run on this host, not only on the developer laptop
