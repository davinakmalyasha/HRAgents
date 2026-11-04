-- Evolve the v1 `import_runs` job table for `hragents-export/1` imports.
-- The v1 columns (source/status/rows/errors) stay; the import needs a content
-- hash for idempotent re-runs, the export format, and per-table outcomes.

ALTER TABLE import_runs ADD COLUMN source_hash TEXT;
ALTER TABLE import_runs ADD COLUMN source_format TEXT NOT NULL DEFAULT 'hragents-export/1';
ALTER TABLE import_runs ADD COLUMN tables_json TEXT NOT NULL DEFAULT '{}';

CREATE UNIQUE INDEX import_runs_source_hash_idx
    ON import_runs(source_hash) WHERE source_hash IS NOT NULL;

PRAGMA user_version = 3;
