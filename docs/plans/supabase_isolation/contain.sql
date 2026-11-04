-- REVIEW DRAFT. Tested on local synthetic PG17.6 only; not applied to production. Emergency containment keeps all imported data.
BEGIN;
ALTER ROLE churchmap_analytics NOLOGIN;
ALTER ROLE churchmap_snapshot_reader NOLOGIN;
-- NOLOGIN does not terminate existing sessions. First stop the analytics
-- workflow and let in-flight transactions end; inspect pg_stat_activity.
-- Do not terminate the runtime application's connections.
ROLLBACK;
