-- 0003_indexes.sql
-- Port the SQLite indexes. Some are different in Postgres: location queries
-- benefit from a B-tree on (latitude, longitude) for the city/state list path;
-- a GIST index on point(longitude, latitude) would be better for radius
-- queries but no current endpoint uses one. Add only what current routes hit.

CREATE INDEX IF NOT EXISTS idx_churches_city_state
    ON churches (lower(city), lower(state));

CREATE INDEX IF NOT EXISTS idx_churches_zip
    ON churches (zip_code);

CREATE INDEX IF NOT EXISTS idx_churches_latlon
    ON churches (latitude, longitude);

CREATE INDEX IF NOT EXISTS idx_churches_external
    ON churches (source, external_id);

CREATE INDEX IF NOT EXISTS idx_churches_enriched
    ON churches (google_enriched_at);

CREATE INDEX IF NOT EXISTS idx_churches_extracted_at
    ON churches (extracted_at);

CREATE INDEX IF NOT EXISTS idx_reviews_church
    ON reviews (church_id);

CREATE INDEX IF NOT EXISTS idx_reviews_user
    ON reviews (user_id);
