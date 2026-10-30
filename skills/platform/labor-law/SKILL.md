---
id: platform.labor-law
name: Indonesian Labor-Law Summaries
description: Use when answering questions about Indonesian employment rules — leave, working time, THR, BPJS, tax structure, termination. Structural explanations with cited sources; never figures.
version: 0.1.0
department: platform
agents: [policy_assistant]
tags: [labor-law, indonesia, ketenagakerjaan, uu-13-2003, cuti, thr, bpjs, pph21]
defer_loading: true
---

# Indonesian Labor-Law Summaries

Short, sourced explanations of the employment rules Rina gets asked about
weekly. They answer "how does this work and where is it configured", not "how
much" — amounts live in operator tables, never here.

## The figures rule

A note may state day and month counts from the cited law (they are the answer
to "how long"). It must never state money, percentages, or multipliers:

- No rupiah figures, no wage caps, no `Rp` / `IDR`.
- No `%`, no `persen` / `percent`, no employer/employee share numbers.
- No multipliers (`1.5x`, `2x`, `×`, `kali lipat`).

Those figures live in the operator's verified rate tables (overtime, BPJS,
PTKP/TER, minimum wage) and leave policies (days per year, accrual). A note
that needs a figure points at the table or policy instead of stating one.

## Every note carries

- `source:` the specific law or regulation (number, year, article where cited).
- `verified_on:` the date the wording was checked against the source.
- A pointer to where the operator's own numbers live.

Law text changes by decree; a note older than its `verified_on` freshness is a
candidate for re-checking, not a statement of current law.

## Answering procedure

1. Search with the user's words, then Indonesian synonyms (cuti, lembur, THR,
   pesangon, PHK, BPJS).
2. Answer the structure, cite the note id and its source law, and name the
   operator table or policy holding the current figures.
3. Add the standing caveat: this is a summary of the cited source for HR
   orientation, not legal advice for a specific case — confirm with the
   operator or counsel.

## Boundaries

- No legal advice for individual cases. Explain the rule, escalate the case.
- No salary commitments, no contract interpretation beyond the note text.
- Never invent a figure the note deliberately omits. If the user presses for
  the current rate, point at the verified table, not at memory.
