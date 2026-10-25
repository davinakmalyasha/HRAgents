# Data governance

What the operator can take with them, what deletion actually does, and who else
touches the data.

**Full export.** Every database row this tenant owns — employees, documents,
leave, payroll, evaluations, approvals, the audit chain — is one JSON document:

```bash
curl -s localhost:8000/v1/export -H "X-API-Key: $KEY" > hragents-export.json
```

The compliance queue has the same action as a download. It is admin-only,
audited (`data.exported`, before the stream starts), and streamed table by
table; the manifest says that each table is its own read snapshot. Binary
attachments live in object storage and are exported from the bucket separately:

```bash
docker compose exec minio mc mirror /data/hragents-documents ./documents
```

**Deletion.** Retention policies and data-subject erasures are
`docs/architecture/` and `/app/w/compliance`: a sweep reports what it purged,
spared, skipped and failed, and a failing handler leaves the record for the next
pass. Payroll is pseudonymized rather than deleted because it is a tax record.
Backups keep their own history until their retention window passes.

**Subprocessors.** A self-hosted install has none of ours: Postgres, Redis,
MinIO and Mailpit run on the operator's host. The operators' own configured
providers (model, email, storage, calendar) are their accounts and their terms.
The DPA template in `docs/legal/dpa-template.md` lists the categories to fill in.
