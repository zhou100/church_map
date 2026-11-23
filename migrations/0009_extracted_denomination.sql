-- What the extractor read on a church's website, kept apart from the directory's
-- denomination. Until now write_extraction overwrote churches.denomination with
-- the model's reading (COALESCE), mixing a machine-read website claim into the
-- directory field that D-1 scope and the visitor-facing label rely on, and
-- discarding the directory value. Additive only: a new nullable column; existing
-- reads and the churchmap_snapshot.churches view are unchanged.
ALTER TABLE churches ADD COLUMN IF NOT EXISTS extracted_denomination TEXT;
