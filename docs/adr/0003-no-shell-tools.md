# ADR 0003 — No shell or command tools, ever

**Status:** accepted · **Date:** 2026-09-12

## Context

LLM agents that can run arbitrary commands turn a prompt-injection payload in a résumé
into arbitrary code execution on the host that holds employee data. Tool-use
capabilities are also the hardest thing to audit: "the agent ran a command" is not an
explainable decision.

## Decision

The tool registry is a closed set of typed, least-privilege tools. There is no shell,
`run_command`, file-system-write, or generic HTTP tool — in code, in configuration, or in
any MCP catalog. Every tool call carries a declared scope, is executed by deterministic
code, and lands on the audit chain. MCP integrations may only register tools from
catalogs that pass the same rule (classified `read`/`write`/`destructive`, with
destructive calls approval-gated).

## Consequences

- Anything the product must do goes through an explicit, testable tool.
- Prompt injection cannot escalate to code execution or data exfiltration beyond the
  declared tool scopes.
- Some automation ideas are simply off the table; new capabilities are added as tools
  with tests, not as shell strings.
