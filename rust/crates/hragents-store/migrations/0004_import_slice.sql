-- Slice-aware idempotency: one import_runs row per (file, slice). The v3
-- single-column unique index wrongly assumed one row per file hash.

DROP INDEX IF EXISTS import_runs_source_hash_idx;

CREATE UNIQUE INDEX IF NOT EXISTS import_runs_source_slice_idx
    ON import_runs(source_hash, tables_json) WHERE source_hash IS NOT NULL;

PRAGMA user_version = 4;
