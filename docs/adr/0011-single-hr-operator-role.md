# ADR 0011 — One `hr_operator` role, one to three local accounts, named-human audit actor

**Status:** accepted · **Date:** 2026-11-01

## Context

Consequential acts — payroll sign-off, erasure, rejection override above the merit floor,
rate-table verification — must name a human. The current product has ten workspaces and
department-shaped surface area; the desktop edition has five surfaces and no employee, manager,
finance or candidate login. A role matrix in a one-to-three-person HR team would be configured
once, wrongly, and then trusted. The control that actually matters is an unlocked session plus
fresh re-authentication, backed by an audit chain.

## Decision

- Exactly one role: `enum Role { HrOperator }`. One to three local accounts with identical
  permissions; a fourth is refused. Accounts are disabled, never deleted, so audit rows keep a
  valid actor; the last active operator cannot be disabled.
- Local login only: Argon2id (m=64 MiB, t=3, p=1, 16-byte salt, 32-byte output). No SSO or
  directory identity, no email reset; the recovery key is the reset path.
- Session states are Locked, Unlocked and Fresh. Re-auth freshness is 5 minutes; consequential
  commands take `Session<Fresh>`, everything else `Session<Unlocked>`.
- The gate is a constructor: `Actor::human(&Session)` is the only route to `ActorKind::Human`.
  IPC structs use `deny_unknown_fields`, so an injected `actor_id` is a deserialization error.
  Agents have no command surface, and `agent` is not a valid audit actor.
- No `rbac.rs`, no `Permission` enum, no segregation of duties. Workspaces are UI surfaces, not
  security boundaries.

## Consequences

Easier: no authorization matrix to misconfigure; every audit row and export names the operator;
one login path to test and one session model to reason about.

Harder: every operator can do everything, so insider risk is bounded by audit and re-auth rather
than authorization; a customer who needs segregation of duties is a server-edition conversation;
a forgotten password without the printed recovery key is unrecoverable data loss.

Out of scope: employee, manager, finance, recruiter or admin roles; SSO; self-registration;
employee self-service; a per-workspace permission model.

Guards: a startup test asserts every consequential command takes `Session<Fresh>`; generated
TypeScript contains no actor field; a negative test rejects `actor_id`; payroll sign-off without
re-auth returns `E_REAUTH_REQUIRED`.
