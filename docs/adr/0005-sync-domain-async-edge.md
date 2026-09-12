# ADR 0005 — Synchronous domain layer; async only at the agent and network edge

**Status:** accepted · **Date:** 2026-09-12

## Context

Postgres persistence must land before the MCP layer, dashboard, and ops work. The
question was how deeply to thread `async` through the codebase. An audit found the real
async zone is narrow: the agent runtime, the pipeline that awaits it, the worker, and two
HTTP clients (`github.py`, file uploads). The domain services and stores — scoring,
policy, approvals, tasks, payroll, compliance, growth, offboarding, recruiting — are
synchronous, and 144 of 145 route handlers never `await` anything.

## Decision

- Domain services and stores stay **synchronous** and remain the behavioral contract.
  The in-memory implementations define it; Postgres adapters implement the same class
  API (subclassing the in-memory class so the type checker enforces the contract).
- Postgres adapters use **synchronous SQLAlchemy over psycopg3**. A `store_backend`
  setting selects `memory` (default; tests, zero-config dev) or `postgres`.
- Store-backed FastAPI routes are **`def`, not `async def`**, so FastAPI runs them in
  the threadpool and blocking database calls never stall the event loop.
- `async` is reserved for code that genuinely awaits I/O: LLM calls (PydanticAI),
  GitHub HTTP, upload reads, and future SSE streaming.
- Alembic keeps its asyncpg URL as a separate process; the app derives its sync URL
  from the same setting.

## Consequences

- The persistence change does not touch service or store test suites, keeping a
  731-test gate stable.
- Concurrency for database-backed routes is bounded by the AnyIO threadpool (40 by
  default) — ample for the self-hosted target; the polish backlog tracks a migration to
  async IO if profiling ever demands it.
- Adapter correctness is testable on SQLite in-memory (same adapter code, different
  engine) and on Postgres in CI, where RLS and JSONB behavior are covered separately.
- Async service code (pipeline, worker, agents) may call sync stores directly; it must
  never be called from a sync route without a clear boundary.
