-- Analytics-only, executed transactionally by cloud_snapshot after safety checks.
-- Deliberately NOT in runtime migrations/: no automatic production deployment.
CREATE TABLE IF NOT EXISTS raw.churches (
 church_id bigint PRIMARY KEY, name text, address text, city text, state text,
 zip_code text, latitude double precision, longitude double precision,
 website text, phone text, source text, external_id text, denomination text,
 has_google_address boolean
);
CREATE TABLE IF NOT EXISTS raw.snapshot_meta (
 snapshot_source text, snapshot_taken_at timestamptz, loaded_at timestamptz
);
ALTER TABLE raw.snapshot_meta ADD COLUMN IF NOT EXISTS snapshot_identity text;
ALTER TABLE raw.snapshot_meta ADD COLUMN IF NOT EXISTS snapshot_scope text;
ALTER TABLE raw.snapshot_meta ADD COLUMN IF NOT EXISTS snapshot_row_count bigint;
ALTER TABLE raw.snapshot_meta ADD COLUMN IF NOT EXISTS snapshot_sha256 text;
ALTER TABLE raw.snapshot_meta ADD COLUMN IF NOT EXISTS snapshot_gate_version text;
