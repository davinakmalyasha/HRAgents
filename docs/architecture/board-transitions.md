# Board Stage Transitions — Manual Move Policy

**Version:** 0.1.0 · **Status:** enforced contract (`services/stages.py`)
**Related:** [HITL bounds](hitl-bounds.md) §3 · [master plan](../plan/master-build-plan.md) §6.3

The pipeline board is derived from deterministic application statuses; cards may be
dragged between columns, but **a drag is only a request**. Every move is validated
server-side against the table below, requires a named human and a reason, and lands
on the hash-chained audit log as `application.stage_changed`. Dragging can never
bypass a HITL gate.

## 1. Statuses and the five columns

| Column | Statuses |
|---|---|
| intake | `queued`, `processing` |
| screened | `evaluated` |
| decision | `gated` |
| interview | `scheduled` |
| closed | `rejected`, `withdrawn` |

Statuses are **derived**: `queued/processing/evaluated/gated/rejected/scheduled` are set
by the worker and the policy engine (see `services/ingestion.py`,
`services/recruiting.py`); this table only governs the additional *manual* moves a
human may request.

## 2. The transition table

Allowed manual moves (`from` → `to`), each requiring `by` (named human) + `reason`:

| # | From | To | Rationale |
|---|---|---|---|
| 1 | `evaluated` | `gated` | Pull a candidate out of the auto-schedule path for review — exercising human oversight (EU AI Act Art. 14), never a negative action |
| 2 | `evaluated` | `withdrawn` | HR or candidate stops the process before a decision |
| 3 | `gated` | `withdrawn` | Stop a gated process; withdrawal is not a rejection |
| 4 | `scheduled` | `withdrawn` | Candidate withdrew or process stopped after scheduling |
| 5 | `scheduled` | `gated` | Undo a schedule (no-show, collapsed plan) back to review |
| 6 | `rejected` | `gated` | Reopen a rejection — the reversal right; auditable, never silent |
| 7 | `withdrawn` | `gated` | Correct an accidental withdrawal |

All other pairs are refused, with distinct server messages so the UI can point at
the right gated flow:

| Refused move | Server message (409) | Correct flow |
|---|---|---|
| any `queued`/`processing` → anything | "set by the worker" | wait for extraction/scoring |
| anything → `rejected` | "record a rejection sign-off first" | review queue → override endpoint (named reviewer + reason code) |
| anything → `scheduled` (e.g. `gated` → interview) | "scheduling is gated" | scheduling proposal / approved override |
| anything → `queued`/`processing`/`evaluated` | "not a manual target" | system-owned states |
| same-status / same-column | "no-op" (409) | — |

## 3. Invariants

1. **Named human, always.** `by` must be a non-empty human identity — never
   `agent:`-prefixed. Agents cannot move cards.
2. **A reason is always required.** Free text, recorded in the audit payload.
3. **No forward shortcut around gates.** `→ rejected` and `→ scheduled` are not in
   the table; they exist only behind the override/scheduling writers.
4. **Reversal is allowed.** Moves 5–7 move *out of* consequential states back to a
   human hold (`gated`) — the EU AI Act Art. 14 ability to reverse stands.
5. **Closed is not frozen.** Only the decision state itself is closed to forward
   motion; reopening is a first-class, audited action.
6. **Everything lands in the chain.** One `application.stage_changed` audit entry
   per move with `{from, to, reason}`; the timeline records `application.stage.<to>`.

## 4. Board behavior (web)

- Cards are draggable (pointer + keyboard sensors). Drops resolve through
  `intentForDrop(currentStatus, targetStage)` in `web/src/features/hiring/pipeline.ts`,
  which mirrors this table for UX routing only — the server re-validates every call:
  - `decision` column → request `gated` (reason dialog)
  - `closed` column → choice dialog: **withdraw** (reason) or **record rejection
    sign-off** (opens the existing override flow; the override endpoint stays the
    only writer of `rejected`)
  - `interview` column → attempt `scheduled` (server refuses; message shown)
  - `intake`/`screened` columns → refused client-side as system-owned
  - same column → no-op
- Server refetch after success is the source of truth; no optimistic card movement.
- The pipeline stays **read-through**: status changes always come back from the API.
