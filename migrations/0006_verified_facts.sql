-- Verified facts from the analytics sidecar (Muse research re-verified on each
-- church's own page). Additive only: new nullable columns and new tables, so no
-- READ_ONLY window is needed and existing reads are unchanged.
--
-- scope_status: NULL is legacy and stays visible. The API hides out_of_scope,
-- not_a_congregation, duplicate and pending (decision D-1); rows are never deleted.
ALTER TABLE churches
    ADD COLUMN IF NOT EXISTS scope_status      TEXT,
    ADD COLUMN IF NOT EXISTS display_tradition TEXT,
    ADD COLUMN IF NOT EXISTS kids_program      TEXT,
    ADD COLUMN IF NOT EXISTS facebook_url      TEXT,   -- never written into website (the crawler reads it)
    ADD COLUMN IF NOT EXISTS service_languages TEXT,   -- as stated, ';'-joined: 'Mandarin;English'
    ADD COLUMN IF NOT EXISTS verified_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS verified_by       TEXT;

-- New congregations are inserted with source = 'muse' and external_id = their
-- candidate ref; re-running the publisher is idempotent on this key.
CREATE UNIQUE INDEX IF NOT EXISTS churches_muse_external_id
    ON churches (external_id) WHERE source = 'muse';

-- One row per published fact: where it was stated and when we checked it. The
-- detail endpoint shows these as "Checked <date>" links. No excerpts are kept.
CREATE TABLE IF NOT EXISTS church_fact_sources (
    church_id       BIGINT      NOT NULL REFERENCES churches(church_id) ON DELETE CASCADE,
    field           TEXT        NOT NULL,
    source_url      TEXT,
    source_type     TEXT,       -- own_site, fb_page, denomination
    checked_at      TIMESTAMPTZ,
    recheck_verdict TEXT,
    run_id          TEXT        NOT NULL,
    PRIMARY KEY (church_id, field)
);

-- One row per written field: the rollback record for scripts/publish_verified.py --revert.
CREATE TABLE IF NOT EXISTS publish_log (
    id           BIGSERIAL   PRIMARY KEY,
    run_id       TEXT        NOT NULL,
    church_id    BIGINT      NOT NULL,
    field        TEXT        NOT NULL,
    action       TEXT        NOT NULL,   -- 'update' or 'insert' (a new congregation)
    old_value    TEXT,
    new_value    TEXT,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS publish_log_run_id ON publish_log (run_id);
