# Runbook: incident response

This is an engineering procedure, not legal advice. Who must be notified, and
within what deadline, is a decision for your counsel and the law that applies to
the deployment. The product tracks the steps and the evidence; a named human
makes each call.

## 1. Contain

- Revoke the exposed API key or provider credential **at the issuer** first.
  Rotating it in HRAgents does not invalidate the old secret.
- Disable the affected provider in `/app/ops` → Connections (or set the
  capability to a non-network provider) and restart the services that built it.
- Do **not** run retention or erasure while evidence is needed. A purge is
  irreversible; if a legal hold applies, record it before anything else.

## 2. Preserve evidence

- The audit chain is append-only. Never edit `audit_log` rows; a manual edit
  breaks the chain and destroys the evidence you are trying to keep.
- Verify the chain before and after any restore:

  ```bash
  docker compose exec api python scripts/verify_audit.py
  ```

- Keep the affected request ids. Every response echoes the correlation id and
  the logs inherit it, so a timeline can be rebuilt without guessing.
- If a restore is unavoidable, use the drill in
  [`deployment.md`](../deployment.md) and re-verify the chain inside the restored
  database before serving traffic.

## 3. Record the incident

Create the breach record and work its checklist rather than tracking steps in a
chat:

```bash
curl -s -X POST "$HOST/v1/compliance/breaches" -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" -d '{"title":"...","summary":"..."}'
curl -s "$HOST/v1/compliance/breaches/overdue" -H "X-API-Key: $KEY"
```

The template endpoint (`GET /v1/compliance/breaches/template`) lists the steps
the deployment tracks. Notifications are recorded with a named human and a
timestamp; a notification that was only discussed is not a notification that
was sent.

## 4. Close

- Rotate every credential that could have been exposed: API keys, the settings
  encryption key, SMTP/IMAP passwords, WhatsApp/Telegram tokens, Google refresh
  tokens, VAPID keys.
- Confirm the audit chain verifies and the breach record is complete.
- Write down what the detection missed and add the check that would have caught
  it earlier. A runbook change is part of the fix.
