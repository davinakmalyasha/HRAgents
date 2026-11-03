# Archive: the Python server product

These documents describe the **Python/FastAPI + Postgres server product**
(HRAgents ≤ 0.15.x): Docker Compose deployment, the FastAPI API, the
Python provider layer, server runbooks, and the Python release machinery.
They are kept for the parity oracle and release archaeology — **not** as
instructions for the current edition.

The current edition is the desktop-first, HR-only cockpit
(Tauri 2.12 + Rust + SQLite, free per-user install). Its source of truth is
[`../../plan/desktop-migration/`](../../plan/desktop-migration/README.md); live status is
[`13-implementation-status.md`](../../plan/desktop-migration/13-implementation-status.md).

## What is here

- `deployment.md` — Docker Compose + Postgres/MinIO/Mailpit operations.
- `api.md`, `api/openapi.json` — the FastAPI surface (frozen spec).
- `architecture/` — pipeline, HITL bounds, Python provider layer, Postgres
  storage, board transitions, server-era benchmarks.
- `runbooks/` — provider failure, incident response, upgrade (Compose-based).
- `data-governance.md`, `fairness.md`, `regions.md` — server-era governance,
  monitoring, and region recipes.
- `paper.md` — the 0.15.x design paper.
- `mcp-server.md`, `mcp-catalog.md` — the Python MCP server and catalog.
- `plan/remaining-work.md`, `plan/polish-backlog.md`, `plan/release-process.md` —
  the Python-product backlog and release machinery (`release-please`, GHCR,
  versioned docs).

## Removed, not archived

`docs/FINAL-SWEEP.md` and `docs/demo-video-script.md` were one-off scratch
files with no live references; they were deleted, not archived. The single
inbound link (an archived `remaining-work.md` footnote pointing at the demo
script) dangles by design — this archive is a snapshot, not a maintained tree.
