-- REVIEW DRAFT. NOT EXECUTED. Emergency containment keeps all imported data.
BEGIN;
ALTER ROLE churchmap_analytics NOLOGIN;
ALTER ROLE churchmap_snapshot_reader NOLOGIN;
-- NOLOGIN does not terminate existing sessions. First stop the analytics
-- workflow and let in-flight transactions end; inspect pg_stat_activity.
-- Do not terminate the runtime application's connections.
ROLLBACK;

-- OPTIONAL removal ONLY before importing data, after stopping both roles.
-- Execute as a separate reviewed transaction. RESTRICT fails if objects exist;
-- it deliberately cannot erase a populated analytics schema.
BEGIN;
DROP SCHEMA raw RESTRICT;
DROP SCHEMA analytics RESTRICT;
DROP SCHEMA analytics_seeds RESTRICT;
REVOKE SELECT (church_id,name,address,city,state,zip_code,latitude,longitude,
  website,phone,source,external_id,denomination,google_address)
  ON public.churches FROM churchmap_snapshot_reader;
REVOKE USAGE ON SCHEMA public FROM churchmap_snapshot_reader;
-- Remove this role's default ACL entries before DROP ROLE, not DROP OWNED.
ALTER DEFAULT PRIVILEGES FOR ROLE churchmap_analytics GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE churchmap_analytics GRANT USAGE ON TYPES TO PUBLIC;
DROP ROLE churchmap_snapshot_reader;
DROP ROLE churchmap_analytics;
ROLLBACK;
