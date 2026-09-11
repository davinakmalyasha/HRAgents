# ADR 0001 — LLMs extract; deterministic code scores

**Status:** accepted · **Date:** 2026-09-12

## Context

Recruiters make initial résumé-fit decisions in roughly 7.4 seconds, and hiring
discrimination has stayed essentially flat for decades. LLM judges reproduce the bias in
their training data, drift between runs and model versions, and give no auditable reason
for a number. Consequential decisions about people need to be reproducible and
explainable.

## Decision

Agents only turn unstructured material (résumés, repositories, documents) into
structured, provenance-tagged facts. Scoring, prioritization, and every automation gate
are hand-specified deterministic functions in `src/hr_agents/services/`:

- the weighted tensor score `S ∈ [0,1]^4`,
- the priority function `P = α·S̄ + β·e^(−λ·Δt) + γ·A − δ·R`,
- the policy gates (`S_tech ≥ 0.85 ∧ σ ≤ 0.05` for auto-scheduling).

Retrieval (RAG) may add recall and answer policy questions; it never computes scores.

## Consequences

- Same input, same score — every component cites its evidence.
- Changing the model can change extraction quality, never a decision. Extraction quality
  is measured separately by evals.
- New signals require explicit scorer changes and tests, not prompt tweaks.
- The LLM cannot be the system of record for anything consequential.
