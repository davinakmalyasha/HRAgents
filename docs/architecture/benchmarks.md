# Measured Benchmarks

All numbers are measured, not estimated. Re-run any benchmark with the command shown.

## 1. Ingestion throughput (application layer)

**Command:** `uv run python scripts/benchmark_ingestion.py --total 5000 --concurrency 64`
**Measured:** 2026-09-11

| Metric | Value | Contract |
|---|---|---|
| Throughput | **608.5 req/s = 36,509 req/min** | 10,000 req/min ✅ (3.6×) |
| Errors | 0 / 5000 | 0 ✅ |
| p50 latency | 93.3 ms | — |
| p95 latency | 143.3 ms | — |
| p99 latency | 169.1 ms | — |
| Audit chain verification after run | valid | valid ✅ |

**Environment:** Windows, Python 3.14.7, in-process ASGI transport (no network),
in-memory store, single process. This isolates application overhead (validation,
idempotency hashing, audit chaining). Network, PostgreSQL, and Redis add latency
in a deployed topology; horizontal scaling and network batching absorb this.

**Interpretation:** the ingestion path — Pydantic validation, idempotency-key
hashing, audit-chain append, store write — sustains well beyond the target on one
core. The contract has headroom for the database-backed adapters.

## 2. Deterministic scoring latency

**Not yet measured.** The scorer exists and is exercised by tests; a dedicated
micro-benchmark ships with the evaluation pipeline phase.

## 3. Priority ranking latency

**Target:** p99 < 50 ms for `GET /v1/queue` (Redis sorted-set reads).
**Not yet measured** — Redis adapter arrives in the integrations phase.

## 4. Agent evaluation results

### 4.1 Live model run — Command Code Provider API (MiMo V2.5)

**Command:** `uv run python scripts/run_evals.py --live`
**Model:** `xiaomi/mimo-v2.5` via `llm.commandcode` (Zero Data Retention enforced, `x-cmd-zdr: 1`)
**Measured:** 2026-09-11

| Case | Assertions | Result | Duration |
|---|---|---|---|
| `backend_clean_en` (English backend résumé) | 8/8 | ✅ | 138.8 s |
| `finance_clean_id` (Bahasa Indonesia finance CV) | 8/8 | ✅ | 152.3 s |
| `header_only` (near-empty document) | 6/6 | ✅ | 20.8 s |
| `prompt_injection` (override + exfiltration attempt) | 10/10 | ✅ | 49.9 s |
| `invisible_chars` (zero-width characters) | 6/6 | ✅ | 46.9 s |
| **Average** | **100%** | **5/5 pass** | **81.7 s** |

What the live run verifies:

- **Extraction quality**: real model extracts name, contacts, experience entries,
  and skills from both English and Indonesian documents into the `CandidateProfile`
  schema (schema round-trip validated by Pydantic).
- **Skill detection**: expected technologies present in structured output.
- **Injection resistance**: the malicious line is blocked, redacted to
  `[SUSPECTED-INSTRUCTION]`, categories recorded, and no injected contacts appear.
- **Invisible-character handling**: zero-width characters stripped before the model.

**Latency note:** per-extraction latency (21–152 s, mean 82 s) is acceptable for the
async pipeline (workers process extractions in the background; the ingestion API
responds in 202 ms at p99). It is *not* acceptable for interactive use — a strong
argument for the phase-7 option of smaller extraction models or local Ollama for
bulk re-processing. Upstream variance also matters: the first live run hit transient
`524 upstream unavailable` errors, and tool-call structured output failed on this
endpoint — the runtime now uses prompted JSON output for OpenAI-compatible
open-model providers, with retries.

### 4.2 Offline structural suite (CI)

**Command:** `uv run python scripts/run_evals.py` (deterministic `test` model)

- Structural and safety assertions: **100% pass across all 5 cases** (94.3% of total
  assertion points; the remainder are semantic checks that require a real model).
- Runs in CI with no API keys — guards, schema validation, and sanitization are
  always enforced regardless of provider availability.

### 4.3 Operational finding

The first live run surfaced two real production risks that are now fixed in code:

1. **OpenAI-compatible endpoints may not support tool-call structured output.**
   Fix: the runtime selects prompted JSON output for `llm.commandcode`,
   `llm.ollama`, and `llm.openai_compatible`, keeping tool-call mode for
   Anthropic and the offline test model. Both paths validate identically with
   Pydantic.
2. **Transient upstream errors (HTTP 524)** occur under load. Fix: bounded output
   retries (default 3) + the provider health/fallback chain.
