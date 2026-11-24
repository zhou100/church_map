-- Program extraction can now end with "unconfirmed_site": the church's
-- website could not be tied to this church (a denomination-wide site such as
-- jw.org shared by many records, or pages that never name this church), so no
-- model call is made and no program is shown for it. See
-- backend/scrapers_v2/programs.py site_is_this_church.
--
-- Only the CHECK constraint on church_program_extractions.status changes: no
-- column is dropped or retyped, so no view can depend on what changes.
-- 0007 created the constraint inline, so Postgres named it
-- church_program_extractions_status_check.
--
-- Re-adding the constraint scans the table under an ACCESS EXCLUSIVE lock.
-- The table holds one row per extracted church; give up after 10 s rather than
-- queue live reads behind a long extraction transaction.
SET LOCAL lock_timeout = '10s';

ALTER TABLE church_program_extractions
    DROP CONSTRAINT IF EXISTS church_program_extractions_status_check;
ALTER TABLE church_program_extractions
    ADD CONSTRAINT church_program_extractions_status_check
    CHECK (status IN ('ok', 'no_program_text', 'error', 'unconfirmed_site'));
