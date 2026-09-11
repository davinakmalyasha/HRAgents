# Automation Boundaries: HITL vs. Full Automation

**Version:** 0.1.0 · **Status:** frozen contract

This document defines exactly where the system may act alone and where a named human must
decide. The rules are enforced by the policy engine — not by convention, not by prompt text.

## 1. Core principle

> Automate **reading, arithmetic, logistics, and reversible positive actions**.
> Reserve human judgment for **consequential negative actions**, **anomalies**, and
> **resource constraints**.

This maps directly to regulatory duties: EU AI Act Art. 14 requires effective human oversight,
including the ability to disregard, override, reverse, and interrupt; GDPR Art. 22 restricts
solely automated decisions with significant effects; UU PDP requires lawful, purpose-bound
processing with data-subject rights.

## 2. Full automation bounds

The system may act without human involvement only when **all** conditions hold.

### 2.1 Auto-scheduling

```
AUTO_SCHEDULE  ⟺  S_tech ≥ 0.85
                ∧ σ ≤ 0.05
                ∧ flags = ∅
                ∧ mutual_slots ≥ min_interviewer_slots (default 2)
                ∧ consent.active = true
```

- `S_tech` — weighted mean of the four-dimension score tensor across k=3 independent runs.
- `σ` — population standard deviation of per-run scores; measures extraction/scoring stability.
- Scheduling is **reversible and positive**: a wrong schedule wastes an hour; it does not deny
  anyone an opportunity. Even so, the candidate must confirm the slot, and any party can reschedule.

### 2.2 Automatic rejection (narrow)

```
REJECT_AUTO  ⟺  S_tech < 0.70 ∧ flags = ∅ ∧ consent.active = true
```

- Only below the technical-merit floor, with no anomalies, and always accompanied by a feedback
  report and an audit entry.
- This path exists because a documented, explainable, low-score rejection is strictly more humane
  than silence. Every such rejection includes the dimension breakdown.

### 2.3 Real-time queue ranking

Priority computation and queue reads are fully automated (deterministic, inspectable):

```
P(c) = α·S̄(c) + β·e^(−λ·Δt) + γ·A(c) − δ·R(c)
```

- Defaults: `α=0.55, β=0.25, γ=0.10, δ=0.10, λ=0.05/h`; ties broken by earliest submission.
- Ranking is **visibility**, not elimination — every candidate remains in the queue and is
  readable; ranking never deletes or rejects.

## 3. Human-in-the-loop override triggers

Any single trigger routes the case to a named human queue. HITL cannot be bypassed by
configuration in production; changing thresholds is itself an audited, human-approved act.

### 3.1 Soft-rejection safeguard (mandatory)

```
0.70 ≤ S_tech < 0.85  →  HITL_SOFT_REJECTION
```

- A rejection notification **may not be sent** until an Engineering Lead (or configured
  equivalent role) signs off with a `reason_code`.
- Default if no sign-off within **72 hours**: escalate to `HITL_MANUAL`. The candidate is
  **never silently rejected** — the failure mode of inaction is advancement to human review,
  not rejection.
- The reviewer sees the full deterministic breakdown plus evidence references, and may:
  - concur with rejection (`reject_requires_signoff`), or
  - overturn to advance (`human_review`).

### 3.2 Anomaly detection

Flag-driven, regardless of score:

| Flag | Trigger |
|---|---|
| `anomaly_experience_format` | Skill scores high but experience timeline violates expected formats (overlaps, gaps > 18 months unexplained, title/date inconsistencies) |
| `low_confidence_extraction` | Any critical field confidence below threshold after retries |
| `inconsistent_runs` | σ > 0.10 between independent extraction/scoring runs |
| `certification_mismatch` | Claimed credential fails registry verification or credential ID conflicts |
| `injection_suspected` | Untrusted content attempted model instruction override |
| `calendar_constraint` | Mutual interviewer slots < `min_interviewer_slots` (default 2) |

Anomalies **never** auto-advance and **never** auto-reject. They are decisions about
uncertainty, and uncertainty is a human problem.

### 3.3 Calendar collisions

```
mutual_slots < 2  →  HITL_CALENDAR
```

- The recruiter/lead resolves by releasing capacity, expanding interviewer pool, or negotiating
  a slot outside the normal window.
- Candidate communication continues during resolution (no silent gaps).

## 4. Complete decision table

Evaluated top to bottom; first match wins.

| # | Condition | Decision | Actor |
|---|---|---|---|
| 1 | `consent.active = false` | halt processing | system (audited) |
| 2 | `flags ≠ ∅` (any) | `HITL_ANOMALY` | human reviewer |
| 3 | `mutual_slots < min_interviewer_slots` | `HITL_CALENDAR` | recruiter/lead |
| 4 | `S_tech ≥ 0.85 ∧ σ ≤ 0.05` | `AUTO_SCHEDULE` | system |
| 5 | `0.70 ≤ S_tech < 0.85` | `HITL_SOFT_REJECTION` | engineering lead sign-off required |
| 6 | `S_tech < 0.70` | `REJECT_AUTO` | system (+ feedback + audit) |

## 5. Override semantics

- Overrides are **append-only**. A new override supersedes an earlier one; nothing is deleted.
- Required fields: `reviewer_id`, `reviewer_role`, `override_decision`, `reason_code`.
- Every override writes an audit entry whose `actor_type = human`, chained to the prior hash.
- The candidate notification is sent **after** the override entry is persisted — never before.
- Reviewer identity is immutable; anonymous overrides are rejected at the API boundary.

## 6. Escalation matrix and SLAs

| Event | SLA | Escalation path |
|---|---|---|
| Soft-rejection sign-off | 72 h | → `HITL_MANUAL`; candidate advances to human review by default |
| Calendar constraint | 48 h | → recruiter lead + hiring manager |
| Anomaly review | 48 h | → engineering lead |
| Candidate message response | 24 h | async agent replies; human handoff on ambiguity |
| Rejection feedback delivery | 7 days | automated from breakdown; human review on request |

## 7. Anti-goals (hard prohibitions)

1. **No auto-rejection with flags present** — uncertainty always summons a human.
2. **No learning from historical hiring outcomes** — the Amazon 2018 failure mode; ranking is a
   hand-specified function, never fitted to past decisions.
3. **No protected attributes in scoring** — verified by counterfactual audit (name/attribute swaps
   must not change scores), per the audit-study methodology in the literature review.
4. **No invisible ranking** — every score is inspectable with evidence references; ranking is
   visibility, not elimination.
5. **No silent candidate experience** — every path ends in a communicated, documented outcome
   within SLA.
6. **No unaudited human action** — overrides are named and chained; anonymous overrides are invalid.

## 8. Regulatory mapping

| Requirement | Where satisfied |
|---|---|
| Human oversight, override/reverse/interrupt (EU AI Act Art. 14) | Policy engine gates; override API; kill-switch per tenant |
| Record-keeping / logs (EU AI Act Arts. 12, 19) | Hash-chained audit log |
| Transparency / explanation (EU AI Act Arts. 13, 86) | Score breakdown + evidence refs + feedback reports |
| No solely automated significant decisions (GDPR Art. 22) | Soft-rejection safeguard; human intervention paths |
| Lawful basis, purpose limitation, rights (UU PDP 27/2022) | Consent records; retention fields; access/correction/erasure workflows |
| Risk governance (NIST AI RMF) | Thresholds snapshotted per decision; fairness harness; audit verification job |
