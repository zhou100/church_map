-- Children's, youth and childcare programs read from each church's archived
-- pages (docs/plans/crawler_visit_facts_plan.md, appendices A and B).
-- Additive only: two new tables, nothing existing changes, so no READ_ONLY
-- window is needed. churches.kids_program and church_fact_sources (Muse,
-- migration 0006) stay as they are and keep their own provenance.
--
-- A row is a website claim: the excerpt was found verbatim, exactly once, in
-- the text of the archived page it cites. That proves the text is there, not
-- that the program still runs as described, so the API labels it as stated
-- on the church's website with the page's fetch date.

CREATE TABLE IF NOT EXISTS church_programs (
    id                BIGSERIAL   PRIMARY KEY,
    church_id         BIGINT      NOT NULL REFERENCES churches(church_id) ON DELETE CASCADE,
    -- NULL when the page does not say when or what kind of program it is.
    program_type      TEXT        CHECK (program_type IN ('during_service', 'weekday_care', 'other')),
    -- Only bands the page itself supports; empty means ages not stated.
    -- young_adult is kept apart so a college group is never a youth group.
    age_bands         TEXT[]      NOT NULL DEFAULT '{}'
                        CHECK (age_bands <@ ARRAY['preschool', 'children', 'youth', 'young_adult']),
    name_stated       TEXT,
    ages_stated       TEXT,
    schedule_stated   TEXT,
    campus_stated     TEXT,
    excerpt           TEXT        NOT NULL,
    -- Character offsets of the excerpt in the page text (programs.page_text),
    -- whose SHA-256 is text_sha256; raw_sha256 is the archived HTML bytes.
    excerpt_start     INT         NOT NULL,
    excerpt_end       INT         NOT NULL,
    source_url        TEXT        NOT NULL,
    artifact_id       BIGINT      REFERENCES raw_crawl_artifacts(id) ON DELETE SET NULL,
    r2_key            TEXT,
    content_hash      TEXT,
    raw_sha256        TEXT        NOT NULL,
    text_sha256       TEXT        NOT NULL,
    page_fetched_at   TIMESTAMPTZ NOT NULL,
    evidence_class    TEXT        NOT NULL DEFAULT 'website_claim',
    extractor_version TEXT        NOT NULL,
    model             TEXT,
    extracted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_church_programs_church ON church_programs (church_id);

-- One row per church: which archived pages the last program extraction read.
-- A church is due again only when that set changes (a changed page is a new
-- artifact id; an unchanged re-fetch keeps its id), never because the
-- extractor version moved: re-extraction after a prompt change is deliberate.
CREATE TABLE IF NOT EXISTS church_program_extractions (
    church_id          BIGINT      PRIMARY KEY REFERENCES churches(church_id) ON DELETE CASCADE,
    input_artifact_ids BIGINT[]    NOT NULL,
    status             TEXT        NOT NULL CHECK (status IN ('ok', 'no_program_text', 'error')),
    error_detail       TEXT,
    pages_read         INT         NOT NULL DEFAULT 0,
    programs_kept      INT         NOT NULL DEFAULT 0,
    programs_dropped   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    extractor_version  TEXT        NOT NULL,
    model              TEXT,
    extracted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
