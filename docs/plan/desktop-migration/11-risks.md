# 11 — Risks, Open Decisions, and Non-Goals

**Status:** draft for implementation · **Scales:** likelihood and impact are **H / M / L**. Review weekly; update at every gate. R1, R2, R4, and R11 are release-blocking.

## 1. Risk register

| ID | Risk | L | I | Mitigation | Owner | Trigger |
|---|---|---|---|---|---|---|
| R1 | Rust rewrite changes behaviour | H | H | Port module by module behind parity; no behaviour changes during port; two reviewers for money and audit; negative tests first | Core lead | Any parity diff; escaped defect in pilot |
| R2 | Payroll does not match Python | M | H | Freeze the oracle; 60 exact scenarios; dual-run until G5; named operator sign-off; never ship with a diff | Payroll lead | Any monetary diff; unverified rate table; export mismatch |
| R3 | AI provider or structured output fails | H | M | Adapter conformance suite; schema validation with bounded retry and fallback; pinned models; store raw-output hash | AI lead | Schema failure >2%; provider 5xx >5%; model deprecation |
| R4 | Python leaks into the runtime | M | H | Bundle scan in CI; process test; no sidecar or localhost bridge; Gate 5; document scanner | Platform lead | Python process, binary, or `site-packages` in bundle |
| R5 | SQLite concurrency or corruption | M | H | One process, single writer, WAL, `busy_timeout`, short transactions; `integrity_check` on open/close; online backup; refuse network shares | Data lead | `database is locked`; integrity failure; WAL >500 MB |
| R6 | SQLCipher hurts performance | M | M | Benchmark encrypted vs plain each release; page cache; key in OS keychain; no opt-out in v1; document overhead | Data lead | Read p95 >2× plain or >50 ms; payroll >2 s |
| R7 | Tauri v2/v3 churn | L | M | Pin 2.12; isolate the shell behind an adapter; no v3 until stable and signing is retested; watch advisories | Platform lead | Stable v3; v2 CVE; plugin incompatibility |
| R8 | Code signing or notarization fails | M | H | Buy certificate in week 0; sign in CI; notarize every release; keys in HSM/CI secret; clean-VM test | Release lead | SmartScreen warning; notarization rejection; cert expiry <60 days |
| R9 | Windows antivirus blocks install | H | M | Sign binaries; no packers; submit builds for reputation; per-user install; publish false-positive steps | Release lead | Defender quarantine; blocked install; reputation warning |
| R10 | Updater supply chain compromise | L | H | Signed manifests; TLS; staged rollout; rollback; SBOM; reproducible builds; never apply unsigned updates | Platform lead | Signature mismatch; unexpected binary hash; rollback >1% |
| R11 | LLM data leakage or prompt injection | H | H | Redact before send; ZDR/DPA providers; injection guard; no side-effect tools; allowlist; local Ollama option; log hashes, not payloads | AI/security lead | Provider policy change; injection eval fail; egress alert |
| R12 | Document parsing crashes or is exploited | H | M | Parse in a constrained worker; size/type limits; no macros; fuzz; OCR fallback; quarantine failures | Core lead | Parser panic; zip bomb; parse >30 s |
| R13 | Timezone or money drift | M | H | One business clock (`Asia/Jakarta`); integer sen; boundary goldens for midnight, month-end, leap year; ban host-clock dates | Core lead | Boundary test fail; payslip off by one; rounding diff |
| R14 | Scope creep | H | H | Freeze scope from 00/08; change board; new feature requires an explicit cut; gate dates reviewed | Product owner | New surface, role, or connector; gate slip >1 week |
| R15 | Users do not adopt it | M | H | Five-minute demo company; import; pilot; in-app guidance; migration service; feedback loop | Product owner | Pilot activation <50%; task time worse than current; support spike |
| R16 | Single-user limitation bites | M | M | Document one writer per database; OS file lock; 1–3 named operators on one machine; no sync; server-edition trigger | Product owner | Concurrent edit conflict; request for remote or second machine |
| R17 | Data import loses or duplicates records | M | H | Import wizard with dry-run; counts and hash reconciliation; rollback; fixtures; never overwrite; audit every batch | Data lead | Count mismatch; duplicate employees; orphan documents |

## 2. Open decisions

| # | Decision | Options | Recommendation | Decide by | Owner |
|---|---|---|---|---|---|
| D1 | Windows-first vs macOS | Windows first; macOS first; both | Windows first through G6; notarized macOS by week 32 | Week 0 | Product |
| D2 | SQLCipher default | On; opt-in; off | On always, per 04/06; no opt-out in v1; measure <10% overhead | Week 0 | Security |
| D3 | One operator vs multiple HR operators | One; 1–3 same role | 1–3 named `hr_operator` accounts on one machine, one writer; no multi-machine | Week 2 | Product |
| D4 | AI provider set | Single vendor; multi-provider | OpenAI-compatible + Anthropic + Gemini + Ollama; no vendor-exclusive feature | Week 2 | AI |
| D5 | Offline mode | Online-only; deterministic offline; full offline | Deterministic features fully offline; AI degrades; outbound work queues | Week 4 | Product |
| D6 | Backup location | App data; Documents; user-chosen | Default app-data `backups/` as in 04; allow a user-selected external copy; encrypted and tested | Week 4 | Data |
| D7 | Licensing | Apache-2.0; source-available; commercial | Apache-2.0, paid integration/support only, no license gating | Week 0 | Product |

## 3. Non-goals for this edition

- Multi-tenant RLS, multi-company installs, SaaS billing, tenant administration.
- Employee, manager, finance, recruiter, or candidate logins; employee self-service; candidate portal.
- Mobile app, PWA, push notifications, service worker.
- Inbound email, WhatsApp, or Telegram webhooks; MCP marketplace; public API.
- Payroll disbursement, tax filing, or statutory advice.
- Central SSO, high availability, horizontal scaling, server-side retention administration.
- An LLM in any consequential decision path.

## 4. What would trigger a server edition

A server edition is justified only when a real customer requirement cannot be met safely on one machine:

| Trigger | Why desktop cannot absorb it |
|---|---|
| More than 3 HR operators, or more than one machine writing the same company data | SQLite has one writer; file sharing corrupts data |
| Employee, manager, or candidate self-service | Requires many identities, scoping, and inbound sessions |
| Inbound webhooks, public API, or a candidate portal | Needs an always-on endpoint and multi-tenant isolation |
| Multiple companies per operator | Requires tenancy, RLS, and cross-tenant administration |
| Central SSO, audit export, or retention administration | Needs a server-side control plane |
| Sustained >10k employees or >1M documents beyond desktop budgets | Needs a server database and background workers |
| Regulated RPO/RTO or central backup | Needs managed infrastructure and monitoring |

## 5. Stop rules

- Gate 2 or Gate 3 slips more than four weeks: freeze scope, re-baseline, and **do not delete Python**.
- A payroll diff is unresolved after two weeks: stop feature work, assign two engineers, delay G5. Never ship approximate money.
- A feature cannot produce a Python parity corpus: cut it from desktop v1 rather than reimplement blind.
- Two consecutive restore drills fail: block release regardless of the calendar.
- A release-blocking risk trigger stays open at a gate: the gate does not open.
