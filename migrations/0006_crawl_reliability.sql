-- Bounded fetch requests use a durable lease (transaction-pooler safe).
-- No artifact/church data is rewritten by this migration.
ALTER TABLE crawl_runs
    ADD COLUMN request_key TEXT,
    ADD COLUMN heartbeat_at TIMESTAMPTZ,
    ADD COLUMN progress_at TIMESTAMPTZ,
    ADD COLUMN rows_skipped INT NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX uq_crawl_runs_request
    ON crawl_runs (stage, request_key) WHERE request_key IS NOT NULL;

CREATE TABLE crawl_stage_leases (
    stage TEXT PRIMARY KEY CHECK (stage IN ('fetch', 'extract', 'tag')),
    run_id BIGINT REFERENCES crawl_runs(id),
    expires_at TIMESTAMPTZ
);
INSERT INTO crawl_stage_leases (stage) VALUES ('fetch'), ('extract'), ('tag');
