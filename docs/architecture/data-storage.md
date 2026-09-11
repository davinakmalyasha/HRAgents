# Data & Storage Architecture

**Version:** 0.1.0 · **Decision:** PostgreSQL 16 + pgvector for all production workloads; SQLite only as an in-memory test engine.

## 1. The decision

| Concern | Production choice | Why |
|---|---|---|
| System of record | **PostgreSQL 16** (`pgvector/pgvector:pg16` image) | ACID transactions, strong concurrency, JSONB, mature replication, universal managed offerings |
| Candidate/job JSON | **JSONB columns** | Schema-validated at the app boundary (Pydantic v2), queryable and indexable inside the database without migration churn |
| Embeddings / semantic search | **pgvector** (HNSW/IVFFlat indexes) | RAG and candidate↔JD similarity without operating a second datastore |
| Queue & priority ranking | **Redis 7** | Streams for work distribution; sorted sets for sub-50 ms priority reads |
| Documents | **MinIO / S3-compatible** | Large binaries (CVs, portfolios) stay out of the database |
| Tests | **SQLite (aiosqlite, in-memory)** | Zero-infrastructure unit tests; full schema created per test |

## 2. Why PostgreSQL for a hiring platform

1. **Universally supported.** Every serious cloud (AWS RDS/Aurora, GCP Cloud SQL, Azure Database), and
   managed providers (Supabase, Neon, Aiven, Render) offer Postgres. A company will never struggle to
   hire for it or to find a hosting path, including in Indonesia (all major providers operate
   Singapore/Jakarta regions).
2. **One engine covers the workload.** Relational integrity for candidates/applications/evaluations,
   JSONB for evolving profile schemas, full-text search for resume keyword recall, and — with
   pgvector — embedding similarity. No premature polyglot sprawl.
3. **Trust and compliance.** Hiring data is personal data (UU PDP No. 27/2022). Postgres gives us
   row-level security, column encryption options, point-in-time recovery, and auditable access
   control — properties SQLite cannot provide in a multi-user deployment.
4. **Concurrency that matches the product.** Ingestion targets 10,000 req/min across horizontally
   scaled API replicas. SQLite serializes writes (single-writer lock) and has no network protocol;
   it cannot serve multiple instances or handle concurrent writers at this rate.
5. **Vector search without a second system.** Candidate↔job similarity (recall/sourcing aid only —
   see §4) uses pgvector. If the corpus ever makes dedicated vector infrastructure worthwhile,
   the interface is a single repository and can migrate without touching the scoring core.

## 3. Why SQLite still exists in this repo

- **Tests**: in-memory, disposable, no Docker requirement, instant schema creation. The DB layer is
  written against SQLAlchemy's async ORM so the *same* models run on both engines.
- **Practical rule**: anything PostgreSQL-specific (pgvector extension, JSONB-specific indexes,
  `FOR UPDATE SKIP LOCKED` claim queries) is exercised in integration tests against the real
  container, not in unit tests against SQLite.

## 4. RAG and vector usage policy

- Embeddings are used for **recall and suggestion**: "similar candidates," "similar open roles,"
  deduplication assistance.
- Embeddings are **never** used to compute the score tensor `S`. Scoring remains the deterministic,
  hand-specified function — the property that makes decisions auditable and defensible.
- This separation is a deliberate design constraint from the evidence base (literature review §3):
  learned similarity ranking reproduces historical bias; deterministic scoring does not learn from
  outcomes.
- Future table: `candidate_embeddings(id, candidate_id, model, embedding vector(1536), created_at)`
  with an HNSW index; added by migration when the embedding pipeline lands.

## 5. Operational profile

| Aspect | Setting |
|---|---|
| Migrations | Alembic (`migrations/`), reviewed before deploy |
| Connection pooling | `asyncpg` via SQLAlchemy `create_async_engine`, pool_pre_ping enabled |
| Backups | Daily snapshot + WAL archiving (managed provider feature) |
| Multi-tenancy | Tenant scoping in queries + RLS policies (planned; see roadmap) |
| Retention | `candidates.retention_expires_at` + scheduled purge job (UU PDP alignment) |
| Encryption | TLS in transit; storage-level encryption at minimum; column encryption for contact fields as hardening step |

## 6. When to revisit

- **Stay on Postgres** for the first several million candidate rows — it handles them comfortably.
- Consider a dedicated search/vector engine (OpenSearch, Qdrant, etc.) only when measured latency or
  cost demands it, and then only for the recall path. Postgres remains the system of record.
