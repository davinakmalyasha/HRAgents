# Demo video script — ingest → review → override → schedule (2–3 minutes)

One continuous screen recording with voice-over. Every shot below uses the
seeded demo dataset, so nothing is staged: `docker compose exec api uv run
python scripts/seed_demo.py` creates five employees mid-onboarding, a hiring
pipeline, a pending leave approval and a payroll run through the real services.

Recording setup: 1440×900 browser window, dashboard at `/app`, Bahasa
Indonesia or English (the switcher is in the topbar — pick one and keep it).
Log in with the operator key from `setup.py`. No editing required; pauses are
fine, retakes are cheap.

## Shot 1 — Home: the work that needs a human (0:00–0:30)

Open `/app`. The attention feed lists what needs a person today: overdue
approvals, overdue tasks, open handoffs — each deep-linking to its queue.

> "HRAgents is a virtual HR team for a one-person HR department. This is the
> home screen: not metrics, just what needs a human today, and where."

## Shot 2 — Ingest: CSV import with consent (0:30–1:00)

Open Hiring → Import. Paste two CSV rows, tick the consent confirmation, submit.
Show the per-item conflict report.

> "Applications come in through import or the API. Consent is captured, never
> inferred — the pipeline refuses to evaluate without it. Every submission is
> accepted with 202 and evaluated asynchronously by the worker."

## Shot 3 — Review: evidence, not a score (1:00–1:40)

Open an application from the pipeline board. Show the evaluation card: score
vector, run agreement, rubric family and digest, evidence references, flags and
the routing recommendation. Expand one dimension to its evidence refs.

> "The score is deterministic — same input, same score, every time — and every
> number cites the résumé text behind it. A dimension with no evidence scores
> zero, which routes the candidate to a human instead of auto-rejecting."

## Shot 4 — Override: the named human decides (1:40–2:20)

Open the review queue. Pick a gated application, enter a decision with a reason
code, and show the audit receipt. Then open Approvals and decide the pending
leave request the seed created.

> "Nothing consequential happens without a named human and a reason. Overrides
> are append-only — the original score stays on the record — and every decision
> lands on a hash-chained audit log you can verify."

## Shot 5 — Schedule and close (2:20–2:50)

Open Scheduling for an auto-scheduled candidate: the free/busy proposal, the
confirm step, and the queued message in Communications with its `mark sent`
evidence.

> "High-confidence positives schedule themselves against free/busy windows;
> everything else waits for a person. That is the whole product: agents read
> and draft, code scores, humans decide."

## Recording checklist

- [ ] Fresh `seed_demo.py` so IDs and queues match this script
- [ ] One language for the whole take
- [ ] Keystrokes visible; no secrets on screen (the API key lives in the
      sign-in form only — clear it before recording the login shot, or record
      login last and cut it)
- [ ] Export 1080p, upload unlisted, embed link in `landing` docs section and
      tick the remaining-work item
