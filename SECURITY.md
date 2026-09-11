# Security Policy

## Reporting a vulnerability

Use GitHub's private advisory flow:
<https://github.com/davinakmalyasha/HRAgents/security/advisories/new>

Do not open a public issue for a vulnerability. Include the affected version or commit,
impact, reproduction steps, and any suggested fix. You can expect an acknowledgement
within 72 hours and a status update within 7 days. Please allow a fix to be published
before public disclosure (we aim for 90 days) — reporters are credited on request.

## Supported versions

Pre-1.0, only the latest `main` and the latest tagged release receive security fixes.
There are no backports before 1.0.

## Scope

In scope: the API, agent runtime, provider adapters, database schema and migrations, and
the audit chain in this repository. Out of scope: third-party services (LLM providers,
WhatsApp Business API, Google APIs) and deployments altered by the operator.

## What matters most here

HRAgents processes personal data and can influence high-impact decisions, so these areas
get extra scrutiny:

- **Prompt injection** — documents are untrusted input
  (`src/hr_agents/agents/injection_guard.py`). Bypasses that let document content change
  scoring, gates, or tool behavior are critical.
- **Human-in-the-loop bypass** — any path that schedules, rejects, purges, or completes
  a consequential action without the coded human gate is critical.
- **Auth and secrets** — API keys, webhook signatures, credential masking, provider
  secrets in logs.
- **Audit integrity** — breaking, truncating, or silently rewriting the hash chain.
- **Data protection** — erasure, retention, consent flows, and PII leakage.

## Secret handling for contributors

- Never commit real credentials; `.env` stays local and is git-ignored.
- CI scans the full git history with gitleaks, and GitHub push protection is enabled.
- If a secret does leak, rotate it immediately and report it via the advisory flow so
  history can be cleaned.
