-- OPTIONAL removal ONLY before importing data, after stopping both roles.
-- Execute as a separate reviewed transaction. RESTRICT fails if objects exist;
-- it deliberately cannot erase a populated analytics schema.
BEGIN;
-- PG16+; same provisioning administrator with retained ADMIN membership.
GRANT churchmap_analytics TO CURRENT_USER WITH INHERIT FALSE, SET TRUE;
SET LOCAL ROLE churchmap_analytics;
DROP SCHEMA raw RESTRICT;
DROP SCHEMA analytics RESTRICT;
DROP SCHEMA analytics_seeds RESTRICT;
-- Remove this role's default ACL entries before DROP ROLE, not DROP OWNED.
ALTER DEFAULT PRIVILEGES FOR ROLE churchmap_analytics GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE churchmap_analytics GRANT USAGE ON TYPES TO PUBLIC;
RESET ROLE;
-- Reject changes to this admin-owned view before removal; verify definition
-- and ownership against the provisioning record. Dropping a view removes no data.
DROP VIEW churchmap_snapshot.churches RESTRICT;
REVOKE USAGE ON SCHEMA churchmap_snapshot FROM churchmap_snapshot_reader;
DROP SCHEMA churchmap_snapshot RESTRICT;
DROP ROLE churchmap_snapshot_reader;
DROP ROLE churchmap_analytics;
ROLLBACK;
