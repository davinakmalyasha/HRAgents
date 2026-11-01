# ADR 0015 — Python stays the offline parity oracle until Gate 5 and never ships

**Status:** accepted · **Date:** 2026-11-01

## Context

The Python implementation defines today's behaviour and carries roughly 2,200 tests. Porting
thirteen domain modules to Rust risks silent drift, especially in scoring, policy and payroll.
Big-bang deletion discards the only oracle; a Python sidecar or localhost bridge keeps two
runtimes in the installer, which `09-sequence.md` §7 forbids because it is a second runtime to
secure and debug.

## Decision

- Python lives in `legacy/python/`, tagged `oracle-0.19.0` with a SHA-256 manifest, and is
  **never** in the installer: no sidecar, no embedded interpreter, no bridge.
- `scripts/parity_export.py` imports the Python services directly (no HTTP, no database) and
  writes `parity/cases|golden/<module>/<case>.json`; `scripts/parity_verify.py` fails if the
  oracle moved, so regeneration is always a reviewed diff.
- `hragents-parity` replays the same cases through the real Rust core with `insta` and prints
  the JSON pointer of the first mismatch.
- `divergences.toml` records known Python defects, is shrink-only, and fails the build if it
  grows. A `base: "spec"` case needs a written rule and two approvals.
- Python is deleted only after the first signed release and a frozen, signed parity corpus.
  After Gate 5, goldens are test data and new cases need two reviewers.

## Consequences

Easier: every port has an objective oracle; slices merge independently; no dual-write and no
second source of truth in production.

Harder: two toolchains stay green in CI until Gate 5; a Python behaviour change requires a
re-export, so the oracle is frozen by policy, not by tooling; corpus governance — hashes,
approvals, divergence entries — is real recurring work; deletion waits for evidence, not a date.

Out of scope: Python at runtime, hidden sidecars, localhost bridges, dual-write, and regenerating
a Python-based golden from Rust behaviour.

Guards: the bundle scan fails on any Python binary, interpreter DLL or `site-packages`; a process
test asserts no interpreter is spawned; `divergences.toml` growth fails CI; Gate 5 requires five
journeys on a packaged build, a green parity suite and an archive of the Python source.
