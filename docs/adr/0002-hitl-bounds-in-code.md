# ADR 0002 — Human-in-the-loop bounds enforced in code

**Status:** accepted · **Date:** 2026-09-12

## Context

"Human oversight" is usually a policy promise, and promises are easy to bypass under
product pressure. Recruiting AI is classified high-risk (EU AI Act, Annex III(4)(a)) and
solely automated consequential decisions are restricted (GDPR Art. 22). The product
philosophy — agents propose, humans decide — is only credible if the software physically
cannot do otherwise.

## Decision

Every consequential boundary is enforced in deterministic code, not prompts or
documentation:

- Auto-scheduling is allowed only for high-confidence positive outcomes
  (`S_tech ≥ 0.85 ∧ σ ≤ 0.05`); everything else routes to a human.
- Rejections at or above the merit floor (`0.70`) require a named human sign-off;
  agents cannot approve, complete, or reject through the approval engine.
- Overrides are append-only, role-restricted, reason-coded, and never anonymous.
- Erasure, purge, waive, and final-pay actions are separate human steps.
- Agents may request approvals or open tasks; they can never complete them.

## Consequences

- Negative tests for every gate are part of the definition of done.
- The UI cannot offer "approve all" shortcuts around these paths.
- Automation coverage is intentionally lower than what a purely automated product could
  advertise — that is the point.
