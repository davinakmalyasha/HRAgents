# ADR 0004 — Capability/provider abstraction for every external dependency

**Status:** accepted · **Date:** 2026-09-12

## Context

Small companies run on whatever they already have: WhatsApp, Gmail or Outlook, local
files or Drive, a local model or an API key. A self-hosted HR system that requires one
specific vendor (or a cloud key) cannot be adopted by the "HR department of one" this
project targets. Vendor SDKs also creep into core code, making tests network-bound and
replacement expensive.

## Decision

Every external dependency is a capability with interchangeable providers behind a single
interface (`ProviderSpec`, `health_check`, `mask_secrets`). Nine capabilities ship with
multiple providers — LLM, email, WhatsApp, Telegram, calendar, storage, embeddings,
vector store, queue — including zero-config defaults (`storage.local_disk`,
`queue.redis`, `embeddings.hash`, `whatsapp.manual_links`. Configuration comes from
environment or the UI; UI wins, environment can lock. The offline `test` model keeps the
whole system runnable and testable with no keys and no network.

## Consequences

- Core code depends on interfaces, never vendor SDKs; every provider has a conformance
  test and a health check.
- Tests stay offline and deterministic.
- Adding a vendor is one file plus tests, not a refactor.
- Some provider features are only available on some backends; the capability interface
  must expose a capability matrix rather than pretend parity.
