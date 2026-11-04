# ADR 0016 — The desktop edition does not grow a server; a future Axum/Postgres edition reuses the core

**Status:** accepted · **Date:** 2026-11-01

## Context

Real customer needs will push toward employee self-service, manager logins, inbound
WhatsApp/email webhooks, a candidate portal, multi-company operation and SSO. Each is cheap to
describe and expensive to carry: a public endpoint needs always-on hosting, identity for many
users, tenancy and a different security model. The desktop app has no public URL, one writer and
one company. `11-risks.md` §4 lists the triggers that justify a separate edition rather than
stretching this one.

## Decision

- The desktop edition adds no multi-user webhooks, no portals, no public API, no SSO, no
  multi-company operation and no horizontal scaling. This is a scope rule, not a backlog item.
- The reusable asset is `hragents-core` (pure, no I/O, no Tauri) plus the `hragents-app` use
  cases. A server edition is an Axum adapter in `hragents-api` behind `--features server`, with
  Postgres and multi-user authentication.
- `axum` never enters the default build: CI asserts `cargo tree --no-default-features` contains
  no `axum`, and the packaged bundle contains no listener.
- ADR 0006 (`tenant_id` with forced RLS) remains the tenancy decision for that edition; the
  desktop schema (ADR 0010) deliberately does not carry it.

## Consequences

Easier: the desktop keeps one writer, a small attack surface and the ≤35 MB installer; the core
stays portable because it has no infrastructure dependency, so both editions can share it.

Harder: saying no to a paying customer whose need is legitimate; the server edition needs its
own auth, tenancy, migration lineage and operations story; core APIs must stay
transport-agnostic, which forbids Tauri or SQLite types leaking into `hragents-core` and
`hragents-app`.

Out of scope for desktop: inbound webhooks, a public API, candidate or employee portals, SSO,
multi-tenant isolation, high availability, server-side retention administration.

Guards: the `cargo tree --no-default-features` axum check; `hragents-parity::boundaries`
asserting crate edges; the G0 test that no port is listening; and the installer size gate, which
bounds what can be linked in unnoticed.
