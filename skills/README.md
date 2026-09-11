# HRAgents Skills

Skills are **content, not code**. Each skill is a markdown runbook the agents load on
demand. Editing a file here changes agent behavior on the next run — no deploy, no code
change. Every skill is versioned and content-hashed; the exact version used is recorded
in every evaluation's audit trail.

## Layout

```
skills/
  <department>/
    <domain>/
      SKILL.md                  # the runbook (required)
      knowledge/                # RAG documents (optional)
        *.md                    # retrieved by the search_knowledge tool
```

- Directory name `<department>` **must** equal `department` in the frontmatter.
- Knowledge documents are scoped to the namespace `<department>.<domain>` and are only
  retrievable by agents with access to that namespace.

## SKILL.md format

```markdown
---
id: recruiting.screening            # stable id; never rename casually
name: Candidate Screening Runbook
description: How to run async candidate screening conversations.
version: 0.1.0
department: recruiting              # must match the top-level folder
agents: [screening_coordinator]     # explicit allowlist — no implicit access
tags: [screening, whatsapp]
defer_loading: true                 # progressive disclosure (default)
---

Write the runbook here. Instructions are what the model receives when it loads
this skill. Be explicit about boundaries, tone, and prohibited actions.
```

### Field reference

| Field | Required | Notes |
|---|---|---|
| `id` | yes | `^[a-z][a-z0-9]*([._-][a-z0-9]+)*$`; unique across all skills; recorded in audit |
| `name` | yes | human title |
| `description` | yes | one line shown in the capability catalog; make it a *when to use* hint |
| `version` | no | semver, default `0.1.0` |
| `department` | yes | must match the top-level directory |
| `agents` | yes | non-empty list of agent names allowed to load it |
| `tags` | no | keywords for search/admin UI |
| `defer_loading` | no | default `true`; `false` places instructions always in the system prompt |

## Knowledge document format

```markdown
---
id: backend-rubric
title: Backend Engineer Evaluation Rubric
tags: [rubric, backend]
---

Content is chunked by heading for retrieval. Keep sections self-contained:
each heading block should make sense on its own.
```

Knowledge is retrieved by the `search_knowledge` tool with citations. It informs
answers and extraction — it is **never** used to compute candidate scores. Scoring
stays deterministic (`docs/architecture/system-architecture.md`).

## Rules

1. **Write boundaries, not vibes.** State what the agent must never do (e.g., never
   promise an outcome, never reveal internal notes, never discuss other candidates).
2. **Cite or omit.** If a runbook makes a factual claim about policy or law, put the
   source in `knowledge/` so the agent can cite it.
3. **One skill, one job.** Split runbooks when they serve different workflows; each
   loads independently.
4. **Never put secrets in skills.** They are versioned content, not configuration.
5. **Hash discipline.** Changing any character changes `content_hash` and shows up in
   the fingerprint — that is intentional and auditable.

## Validation

`uv run pytest tests/skills -q` validates every file in this directory: frontmatter
schema, department consistency, unique ids, and knowledge namespaces.
