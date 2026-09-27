# Provider Layer — Adaptive, Universal Integrations

**Version:** 0.1.0 · **Status:** locked architecture
**Principle:** every external dependency is a *capability* with interchangeable *providers*, selected
by configuration. Companies choose what they use; the system adapts without code changes.

---

## 1. Why this exists

HRAgents must run in wildly different realities:

- A solo HR person with a Gmail account and no server admin
- An SME that insists on WhatsApp and nothing else
- A company with a cloud LLM contract and a policy against data leaving their VPC
- A freelancer (the author) pre-configuring a client's install before handover

One hardcoded integration per need makes all of those impossible. Instead: **one interface per
capability, N providers behind it, one config surface.** Adding a provider is one file — the
settings UI, health checks, and fallbacks are generated from its schema.

---

## 2. Capabilities and providers

| Capability | Providers (planned/active) | Self-host default | Notes |
|---|---|---|---|
| `llm` | `test` (offline) · `ollama` (local) · `commandcode` (all top models, ZDR default) · `openai_compatible` · `anthropic` | `test` until configured | PydanticAI model string derived from config |
| `embeddings` | `hash` (offline, deterministic) · `openai` · `voyage` · `ollama` | `hash` — zero config, zero cost | RAG recall only; never scoring |
| `email_send` | `smtp` (live) · `resend` (config-only) | `smtp` (their existing mailbox) | Resend adapter not implemented yet |
| `email_receive` | `imap_poll` (live) · `resend_webhook` (config-only) | `imap_poll` — no public URL needed | |
| `whatsapp` | `manual_links` (live) · `meta_cloud` (config-only) | `manual_links` (wa.me) until connected | Meta Cloud needs a public HTTPS webhook |
| `calendar` | `google` · `microsoft365` · `caldav` · `manual_slots` | `manual_slots` until connected | ICS invites as universal fallback |
| `storage` | `local_disk` · `s3` (MinIO/R2/AWS) · `gdrive` | `local_disk` in self-host; `s3` in compose | |
| `vector_store` | `in_memory` · `pgvector` | `pgvector` in compose; `in_memory` in tests | Same retriever interface |
| `queue` | `memory` · `redis` (Streams) · `postgres` (SKIP LOCKED) | `redis` in compose | Single conformance suite per backend |

Legend: **active** providers ship with tests; **planned** providers are registered but raise
"not configured" until implemented.

---

## 3. Anatomy of a provider

Each provider is one module that declares a spec. The registry, settings UI, health checks, and
fallback logic all derive from it.

```python
# src/hr_agents/providers/builtin/llm_anthropic.py
from hr_agents.providers.base import Capability, ProviderConfig, ProviderSpec, SecretStr


class AnthropicConfig(ProviderConfig):
    api_key: SecretStr  # flagged secret → masked in UI
    model: str = "claude-sonnet-4-5"
    base_url: str | None = None  # optional proxy/gateway


PROVIDER = ProviderSpec(
    id="llm.anthropic",
    capability=Capability.LLM,
    display_name="Anthropic (Claude)",
    docs_url="https://docs.anthropic.com/",
    config_model=AnthropicConfig,  # → UI form generated from JSON Schema
    build=lambda config: build_pydantic_ai_model(config),
    health_check=lambda config: probe_anthropic(config),
)
```

Rules:

1. **One file per provider.** No provider logic anywhere else in the codebase.
2. **Config model is the contract.** The Settings UI renders forms from the JSON Schema; secrets
   use `SecretStr` and are never rendered, logged, or exported raw.
3. **`health_check` is mandatory.** Returns `ProviderHealth(status, detail, checked_at)` —
   `ok` / `degraded` / `misconfigured` / `unavailable`. The UI shows a badge; the system falls
   back when a capability is unavailable.
4. **No cross-provider imports.** Providers depend only on `providers.base` and their vendor SDK.
5. **Fallbacks are explicit.** A capability declares its fallback chain, e.g.
   `whatsapp → manual_links`, `email_send → smtp`, `llm → test`.

---

## 4. Configuration model

### 4.1 Three surfaces, one source of truth

| Surface | Who uses it | When |
|---|---|---|
| `.env` | Ops / freelancer during deploy | Deploy time; can **lock** a field |
| Setup wizard | First run | Guided: Database → Admin → LLM → Email → WhatsApp (skippable) |
| Settings UI | HR admin | Change provider, rotate keys, test connection |

**Precedence:** UI value wins by default. If an env var explicitly locks a field
(`HRAGENTS_LOCK_llm__api_key=true`), the UI shows a padlock and the env value wins. This lets a
freelancer pre-configure a client's install while solo adopters use the UI freely.

### 4.2 Storage

- Non-secret config: `provider_configs` table (tenant-scoped from Phase 5)
- Secrets: encrypted at rest (application-level encryption key from env); masked in every
  response (`sk-…4f2a`); **never** written to logs or audit payloads — audits record a key hash.

### 4.3 Change discipline

Every provider config change writes an audit entry: who, capability, provider id, changed field
names (values redacted), and the health-check result before/after. Rollback = re-apply previous
entry through the same API.

---

## 5. Graceful degradation matrix

The system must never crash because a provider is missing — it degrades to the documented
fallback and tells the user exactly what is disabled.

| Capability missing | Behavior | User-visible state |
|---|---|---|
| `llm` | Agents refuse to run; deterministic core still works (manual profiles); `test` model in dev/CI | Banner: "No AI provider configured — extraction disabled" |
| `embeddings` | Falls back to `hash` provider automatically | No visible change; retrieval quality note in settings |
| `email_send` | Messages stay queued; the bridge prints a preview and the human sends (or `mark sent` records it) | Banner: "Email not connected — messages stay queued" |
| `email_receive` | Inbound polling is off; replies are still recorded by hand on the application | Settings task: "Configure inbox" |
| `whatsapp` | `manual_links` mode: a wa.me link is composed for the queued message and HR sends it; the dispatch is then recorded like any manual send | Chip: "WhatsApp: manual mode" |
| `calendar` | `manual_slots` mode: HR enters slots; ICS invites generated | Chip: "Calendar: manual mode" |
| `queue` | Always available — memory/redis/postgres are all built-in | None |
| `vector_store` | In-memory fallback for small corpora | None |

---

## 6. Adding a new provider (contributor recipe)

1. Copy the closest existing provider file in `src/hr_agents/providers/builtin/`.
2. Define the config model (Pydantic v2, secrets as `SecretStr`).
3. Implement the adapter functions (`build`, `health_check`).
4. Export `PROVIDER = ProviderSpec(...)`.
5. Add fixtures + a conformance test entry.
6. Done — the registry discovers it, the UI renders it, fallbacks apply.

No frontend changes. No core changes. That is the entire point.

---

## 7. Where each capability is consumed

| Capability | Consumer |
|---|---|
| `llm` | `agents/runtime.py` — resolves the PydanticAI model for every agent |
| `embeddings` | `knowledge/retriever.py` at index-build time |
| `email_send` / `email_receive` | `messaging/smtp.py` + `messaging/outbox.py` (queued outbox) · `messaging/imap.py` + `messaging/inbound.py` (replies) |
| `whatsapp` | `messaging/whatsapp.py` + `messaging/outbox.py` (manual link dispatch) |
| `calendar` | `services/scheduling` (Phase 7) |
| `storage` | `services/documents.py` (currently in-memory; adapter phase 7) |
| `vector_store` | `knowledge/` (pgvector adapter phase 7) |
| `queue` | `services/ingestion.py` JobQueue → provider-backed runtime |

---

## 8. Build order

1. `providers/base.py` — `Capability`, `ProviderConfig`, `ProviderSpec`, `ProviderHealth`, secrets
2. `providers/registry.py` — registration, discovery, resolution, fallback chains
3. `providers/queue/` — `memory` + `redis` + `postgres` (one conformance suite)
4. `providers/llm/` — `test` + OpenAI-compatible builder (covers ollama/openrouter/groq via base URL)
5. Settings resolution (env layer now; encrypted DB layer in Phase 5)
6. `docs/architecture/providers.md` — this document, kept current
