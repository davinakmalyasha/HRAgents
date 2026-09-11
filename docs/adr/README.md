# Architecture Decision Records

Immutable notes for decisions that are expensive to reverse. Each ADR states the
context, the decision, and the consequences we accept. The locked-decisions table in
[`docs/plan/master-build-plan.md`](../plan/master-build-plan.md) stays the summary;
ADRs add the reasoning, and are citable in the paper.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-llm-extracts-deterministic-scores.md) | LLMs extract; deterministic code scores | Accepted |
| [0002](0002-hitl-bounds-in-code.md) | Human-in-the-loop bounds enforced in code | Accepted |
| [0003](0003-no-shell-tools.md) | No shell or command tools, ever | Accepted |
| [0004](0004-provider-layer.md) | Capability/provider abstraction for every external dependency | Accepted |

New ADRs: copy the format of an existing file, number sequentially, open a PR.
ADRs are append-only — to change a decision, add a new ADR that supersedes the old one
and update its status line.
