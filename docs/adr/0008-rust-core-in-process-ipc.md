# ADR 0008 — The Rust core runs in-process behind typed Tauri IPC

**Status:** accepted · **Date:** 2026-11-01

## Context

The UI needs a transport to the domain. Three options were considered: a localhost HTTP server
(the FastAPI shape), a Python sidecar, or linking the Rust core into the Tauri process. A
localhost server means a listening port, CORS, a loopback auth token, a firewall prompt and a
second protocol to secure — and it invites a browser tab to become a second client. A Python
sidecar means a bundled interpreter, a 200–600 ms startup penalty, a second signing target and
a hidden second runtime, which `09-sequence.md` §7 explicitly forbids.

## Decision

- `hragents-core` and `hragents-app` are linked into the Tauri process. There is no HTTP
  listener, no loopback port, no CORS, and no sidecar.
- Every command is `#[tauri::command] #[specta::specta] async fn`; `tauri-specta` generates
  `web/src/lib/ipc/bindings.gen.ts`, which is committed, and CI fails on a stale diff.
- `SessionGuard` is injected by the Rust side, never accepted from JavaScript. Commands take
  `&Session`; an actor id in a request body is a deserialization error.
- Errors are a tagged enum serialized as a stable `{ code, message, details?, retryable }`.
  Reads use cursor pagination; large results stream over `ipc::Channel<T>`.
- Blocking work — SQLite, parsing, XLSX/PDF — runs on `spawn_blocking`; no lock is held
  across `.await`.
- `fetch`, `axios` and OpenAPI clients are banned in `web/src/` by lint rule.

## Consequences

Easier: no port, firewall or CORS surface; IPC read p95 ≤20 ms without an HTTP hop; the command
list is the reviewed contract, and the generated TypeScript is the only client.

Harder: there is no `curl`/Postman or OpenAPI document to debug against, so E2E must drive the
real command or the same typed service; every API change requires regenerating bindings in the
same commit; a UI defect cannot be reproduced in an ordinary browser tab.

Out of scope: an HTTP API for the desktop edition, an MCP server inside desktop, browser access,
a Python bridge.

Guards: the bindings drift test; the G0 smoke test asserting no listening port; and
`hragents-parity::boundaries`, which parses each `Cargo.toml` and asserts the permitted crate
edges.
