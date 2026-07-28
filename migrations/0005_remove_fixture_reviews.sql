-- The original Brooklyn demo reviews were anonymous fixtures, not community
-- submissions. Remove only the audited March 22 fixture set. Current review
-- writes require an authenticated user, so the guards keep later real reviews
-- on these churches intact.
DELETE FROM reviews
WHERE church_id BETWEEN 1 AND 7
  AND user_id IS NULL
  AND reviewer_name IS NULL
  AND created_at < TIMESTAMPTZ '2026-03-23 00:00:00+00';
