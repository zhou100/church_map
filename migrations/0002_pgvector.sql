-- 0002_pgvector.sql
-- Enable pgvector and convert church_embeddings.vector_blob (BYTEA) to a
-- typed vector column. Dimension is read per-row from the existing `dim`
-- column. Decoding from BYTEA -> vector happens in scripts/migrate_data.py
-- because Postgres can't decode raw float32 bytes into a vector literal
-- without a helper. This migration only enables the extension and adds the
-- target column; the data load fills it.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE church_embeddings
    ADD COLUMN IF NOT EXISTS vector vector;
