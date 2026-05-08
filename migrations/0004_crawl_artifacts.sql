-- 0004_crawl_artifacts.sql
-- Phase B: R2-backed crawl pipeline.
--
-- Three new tables:
--   crawl_runs          one row per cron invocation per stage (fetch|extract|tag)
--   raw_crawl_artifacts one row per fetched page; HTML lives in R2, metadata here
--   robots_cache        per-host robots.txt with 24h TTL
--
-- Plus extraction provenance columns on churches so we can baseline against
-- prior prompt/model versions and surface confidence + verbatim source snippets.
--
-- Idempotency: UNIQUE (church_id, url, content_hash) on raw_crawl_artifacts means
-- re-fetching the same page (same body) is a no-op. Re-fetching with a changed
-- body inserts a new row, preserving history.

CREATE TABLE IF NOT EXISTS crawl_runs (
    id              BIGSERIAL PRIMARY KEY,
    stage           TEXT NOT NULL CHECK (stage IN ('fetch', 'extract', 'tag')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'ok', 'error', 'partial')),
    batch_size      INT,
    rows_processed  INT NOT NULL DEFAULT 0,
    rows_ok         INT NOT NULL DEFAULT 0,
    rows_error      INT NOT NULL DEFAULT 0,
    triggered_by    TEXT,
    error           TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_crawl_runs_stage_started
    ON crawl_runs (stage, started_at DESC);

CREATE TABLE IF NOT EXISTS raw_crawl_artifacts (
    id                   BIGSERIAL PRIMARY KEY,
    church_id            BIGINT NOT NULL REFERENCES churches(church_id) ON DELETE CASCADE,
    url                  TEXT NOT NULL,
    kind                 TEXT NOT NULL,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    http_status          INT NOT NULL,
    fetch_error          TEXT,
    robots_allowed       BOOLEAN NOT NULL DEFAULT TRUE,
    content_hash         TEXT,
    r2_key               TEXT,
    bytes_raw            INT,
    bytes_text           INT,
    extract_status       TEXT NOT NULL DEFAULT 'pending'
                           CHECK (extract_status IN ('pending', 'ok', 'skipped', 'error')),
    extract_error_detail TEXT,
    extracted_at         TIMESTAMPTZ,
    crawl_run_id         BIGINT REFERENCES crawl_runs(id) ON DELETE SET NULL
);
-- (church_id, url, content_hash) uniqueness allows null content_hash for
-- failed fetches without blocking a future successful fetch from the same
-- url. Postgres treats NULLs as distinct in UNIQUE by default, which is the
-- behavior we want here.
CREATE UNIQUE INDEX IF NOT EXISTS uq_artifacts_church_url_hash
    ON raw_crawl_artifacts (church_id, url, content_hash);
CREATE INDEX IF NOT EXISTS idx_artifacts_church_kind
    ON raw_crawl_artifacts (church_id, kind);
CREATE INDEX IF NOT EXISTS idx_artifacts_extract_pending
    ON raw_crawl_artifacts (id) WHERE extract_status = 'pending';
CREATE INDEX IF NOT EXISTS idx_artifacts_fetched_at
    ON raw_crawl_artifacts (fetched_at DESC);

CREATE TABLE IF NOT EXISTS robots_cache (
    host        TEXT PRIMARY KEY,
    body        TEXT NOT NULL DEFAULT '',
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);

ALTER TABLE churches
    ADD COLUMN IF NOT EXISTS extracted_model           TEXT,
    ADD COLUMN IF NOT EXISTS extracted_confidence      JSONB,
    ADD COLUMN IF NOT EXISTS extracted_source_snippets JSONB;
