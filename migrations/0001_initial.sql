-- 0001_initial.sql
-- Phase A: lift-and-shift port of holyhub.db to Postgres.
-- Lowercase table names (Postgres folds unquoted identifiers; quoted mixed-case
-- becomes annoying forever). Wide `churches` row preserved verbatim; future
-- decomposition into church_sources / extracted_attributes / church_tags is
-- Phase C, intentionally not in scope here.

CREATE TABLE IF NOT EXISTS churches (
    church_id              BIGSERIAL PRIMARY KEY,
    name                   TEXT NOT NULL,
    address                TEXT,
    city                   TEXT,
    state                  TEXT,
    denomination           TEXT,
    service_times          TEXT,
    latitude               DOUBLE PRECISION,
    longitude              DOUBLE PRECISION,
    zip_code               TEXT,
    website                TEXT,
    phone                  TEXT,
    source                 TEXT DEFAULT 'manual',
    external_id            TEXT,
    google_place_id        TEXT,
    google_photos          JSONB,
    google_hours           JSONB,
    google_enriched_at     TIMESTAMPTZ,
    google_rating          DOUBLE PRECISION,
    google_review_count    INTEGER,
    google_reviews         JSONB,
    google_editorial       TEXT,
    google_wheelchair      INTEGER,
    google_address         TEXT,
    language               TEXT,
    cultural_background    TEXT,
    website_summary        TEXT,
    extracted_tags         JSONB,
    extracted_at           TIMESTAMPTZ,
    extracted_prompt_version TEXT,
    extracted_status       TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id     BIGSERIAL PRIMARY KEY,
    google_id   TEXT UNIQUE NOT NULL,
    email       TEXT,
    name        TEXT,
    avatar_url  TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id            BIGSERIAL PRIMARY KEY,
    church_id            BIGINT REFERENCES churches(church_id),
    rating               DOUBLE PRECISION,
    comment              TEXT,
    worship_energy       DOUBLE PRECISION,
    community_warmth     DOUBLE PRECISION,
    sermon_depth         DOUBLE PRECISION,
    childrens_programs   DOUBLE PRECISION,
    theological_openness DOUBLE PRECISION,
    facilities           DOUBLE PRECISION,
    created_at           TIMESTAMPTZ DEFAULT now(),
    user_id              BIGINT REFERENCES users(user_id),
    reviewer_name        TEXT,
    reviewer_avatar      TEXT
);

CREATE TABLE IF NOT EXISTS api_usage (
    month   TEXT NOT NULL,
    service TEXT NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (month, service)
);

-- church_embeddings is created here as a placeholder; 0002 swaps the BLOB
-- column for a pgvector typed column once the extension is enabled.
CREATE TABLE IF NOT EXISTS church_embeddings (
    church_id   BIGINT PRIMARY KEY REFERENCES churches(church_id),
    model       TEXT NOT NULL,
    dim         INTEGER NOT NULL,
    vector_blob BYTEA NOT NULL,
    source_text TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);
