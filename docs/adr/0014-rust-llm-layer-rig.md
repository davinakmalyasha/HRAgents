# ADR 0014 — Rust LLM layer on `rig` 0.46 with structured output validated in Rust; agents never decide

**Status:** accepted · **Date:** 2026-11-01

## Context

The Python app uses PydanticAI and a reserved offline `test` model; prompts live under
`src/hr_agents/skills/`. The Rust port needs multi-provider access, streaming, a read-only tool
loop and structured extraction — without becoming a place where a model makes a decision.
`rig` 0.46 covers OpenAI, Anthropic, Gemini, Ollama, OpenRouter and Groq, but it is pre-1.0 and
its API moves.

## Decision

- Use `rig` 0.46.x (or the latest stable at scaffold time), pinned. Only adapters import it,
  behind `agents::Provider` and `agents::Extractor`. Fallback is OpenAI-compatible
  `/chat/completions` over `reqwest`.
- Structured output is a `#[derive(JsonSchema)]` DTO through `Extractor` **plus a Rust
  validator**. Providers without native schemas fall back to prompted JSON through the same
  validator: the validator, not the provider, is the contract.
- The tool loop uses a read-only registry; `request_approval` creates an approval row.
  Destructive calls carry an argument digest so the executed arguments equal the previewed ones,
  at most once.
- Streaming goes to `ipc::Channel<ChatDelta>`. Retries are 3 attempts, 250 ms base, full jitter,
  only on 429/5xx/timeout, behind a per-provider circuit breaker.
- The offline `test` provider is the zero-config default; `ReplayProvider` replays
  `parity/llm/*.jsonl` by request hash. Prompts are embedded with `include_str!`, and a
  whitespace-normalised diff test fails on drift.
- Agents never decide: output is validated data; proposed actions become rows a human executes;
  `agent` is not a valid audit actor.

## Consequences

Easier: one provider abstraction, deterministic offline tests, and a provider swap that never
touches domain code.

Harder: `rig` churn is absorbed in adapters, so an adapter conformance suite is mandatory;
prompt drift tests need maintenance; native schema support differs per provider, so the validator
carries more traffic than expected.

Out of scope: agent write access, model-chosen approvals, an MCP marketplace, network access in
tests, autonomous decisions.

Guards: a no-network test guard; replay fixtures; the prompt diff test; and the crate boundary
that keeps `hragents-agents` unable to depend on `hragents-app`, so no agent has a compile-time
route to a mutating use case.
