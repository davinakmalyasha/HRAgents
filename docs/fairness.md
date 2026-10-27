# Fairness and score monitoring

HRAgents separates two questions that are easy to blur together:

1. **Does the deterministic pipeline ignore non-job-relevant attributes?**
   The counterfactual harness answers this on synthetic pairs and runs in CI.
2. **Is the real scoring path behaving consistently per job?**
   The distribution monitor answers this from evaluations the pipeline actually
   registered.

Neither is a demographic parity measurement. Protected attributes are never
collected or scored, so no report here can compare outcomes by group; the
honest claim is invariance plus per-job drift monitoring.

## Counterfactual harness

`services/fairness.py` scores identical profiles that differ only in a name or
city, and compares the full score vector and weighted total **exactly**. The
pipeline is deterministic, so any change is a defect, not noise. The eval
dataset also carries name-swapped CV pairs compared by a decision signature
(normalized skills, experience shape, education, certifications and the scored
vector) that excludes the swapped name.

CI exercises the wiring with the offline model. A live-model comparison still
needs a provider that accepts the deployment's configuration; see
`docs/plan/remaining-work.md`.

## Per-job distribution monitor

`GET /v1/ops/fairness?days=90` (admin) returns, for every job with evaluations
in the window:

| Field | Meaning |
|---|---|
| `evaluations` | Registered evaluations in the window |
| `mean`, `minimum`, `maximum` | The weighted total (`s_tech`) |
| `bins` | Five half-open bands, `[0.0,1.0]` in 0.2 steps |
| `recommendations` | Routing mix (`auto_schedule`, `human_review`, `reject_requires_signoff`, `reject`) |
| `requires_human` | Human review + sign-off required |
| `flagged` | Evaluations carrying at least one flag |

The report is bounded to the most recent 2,000 evaluations in the window and
sets `truncated` when it clips; the window itself is validated to 1–365 days.
It reads the same registered evaluations the dashboard serves — not fixtures —
so a weight change, an extraction drift or an unusual manual-routing share for
one job becomes visible without a live model call.

The Operations page renders the report as a table under **Score distribution**,
including the API's note that protected attributes are never collected.

### How to read it

- A job whose mean moves while its rubric digest does not is a signal to inspect
  extraction and evidence, not a reason to change thresholds.
- A rising `requires_human` share is the system asking for people; check the
  decision reasons and flags before assuming a candidate-quality problem.
- A spike in `flagged` for one job points at document quality, truncation or
  injection attempts for that intake source.

## What is deliberately absent

- **No protected attributes in the data model.** Adding them to measure parity
  would create the very dataset the product avoids holding.
- **No group-level metric presented as fairness.** The report says what it is on
  screen and in the API note.
- **No automatic threshold change.** Monitoring is a named human's input to a
  deliberate rubric decision, not an auto-tuner.
