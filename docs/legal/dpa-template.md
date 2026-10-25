# Data processing agreement (template)

> **Template, not legal advice.** Have a lawyer review it before use. Replace
> every `[…]` placeholder; delete rows that do not apply. The controller and
> processor roles depend on who operates the instance and for whom.

## 1. Parties

- **Controller:** [legal name, address, contact]
- **Processor:** [legal name, address, contact]

## 2. Subject matter and duration

Processing of employee and candidate personal data for the purposes of
recruitment, employment administration, payroll **preparation**, compliance and
related HR operations, for the duration of the service agreement and the
retention periods in Schedule A.

## 3. Nature and purpose of processing

The processor hosts and operates HRAgents: it stores the data in the controller's
database, runs deterministic scoring and human-in-the-loop workflows, and sends
notifications through the transports the controller configures. The processor
does not decide who is hired, rejected, paid or disciplined; those decisions are
reserved to named humans at the controller.

## 4. Categories of data subjects and personal data

- **Data subjects:** candidates, employees, dependants where applicable,
  interviewers, approvers.
- **Data:** identification and contact data, CV and portfolio content,
  employment and education history, compensation and payroll data, leave and
  attendance, performance and goals, compliance records (consent, retention,
  erasures, incidents), audit-chain entries. [Adjust.]

## 5. Special categories

[State whether any special-category data (health, biometric, union membership)
is processed, or "None".]

## 6. Processor obligations

1. Process only on documented instructions from the controller, including
   transfers, unless required by law (and then inform the controller).
2. Confidentiality: personnel are bound by confidentiality.
3. Security: the measures in Schedule B.
4. Sub-processors: none by default; any addition requires prior written
   authorisation and the same obligations.
5. Assistance: respond to data-subject requests through the controller; the
   product provides erasure, consent and retention workflows and a full export.
6. Breach notification: without undue delay and no later than [24/48/72] hours
   after becoming aware, with the information the controller needs to notify.
7. Deletion or return on termination: [delete/return] within [N] days, subject
   to statutory retention (payroll and tax records are pseudonymized, not
   deleted).
8. Audit: provide the information needed to demonstrate compliance, including
   the tamper-evident audit chain and export.

## 7. Controller obligations

Lawful basis, notices, consent where required, accuracy of instructions, and
the content of the data it loads.

## 8. International transfers

[State the mechanism: adequacy decision, SCCs module, or "none".]

## 9. Liability and governing law

[Per the main service agreement.] Governing law: [jurisdiction].

---

## Schedule A — retention

| Record | Retention | Basis |
|---|---|---|
| Candidate records | [24] months after the last activity | [policy] |
| Employee records | Employment + [N] years | [statute] |
| Payroll and tax | [10] years (pseudonymized) | [statute] |
| Audit chain | [N] years | [policy] |
| Backups | [N] days/weeks | [policy] |

## Schedule B — technical and organisational measures

- Encryption in transit; provider credentials sealed at rest (Fernet) and masked
  in every response.
- Role-based access control and Postgres row-level security per tenant.
- Named-human gates for rejections, payroll sign-off, erasures and overrides.
- Append-only, hash-chained audit log with scheduled verification.
- Retention sweeps with dry-run default and per-record failure reporting.
- No shell or arbitrary-command tools; agents extract and draft only.
- [Host hardening, backup encryption, key custody, logging retention — fill in.]
