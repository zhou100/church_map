-- REVIEW DRAFT. Tested only on synthetic local PG17.6; NOT APPLIED TO PRODUCTION.
-- Default ROLLBACK; not a runtime migration.
-- Before authorized application: save current ACLs; confirm runtime identity,
-- Data API exposure, no schema/role collisions, and database CREATE privilege.
-- Run as an authorized provisioning administrator, never the runtime app.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
DO $$
BEGIN
  IF current_setting('server_version_num')::int < 160000 THEN
    RAISE EXCEPTION 'This draft requires PostgreSQL 16+; confirm project version first';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN
    ('churchmap_analytics','churchmap_snapshot_reader')) THEN
    RAISE EXCEPTION 'Proposed roles already exist; inspect instead of reusing';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname IN
    ('raw','analytics','analytics_seeds','churchmap_snapshot')) THEN
    RAISE EXCEPTION 'Proposed schemas already exist; inspect instead of reusing';
  END IF;
  IF to_regclass('public.churches') IS NULL THEN
    RAISE EXCEPTION 'Expected source table missing';
  END IF;
  IF (SELECT pg_get_userbyid(relowner) FROM pg_class
      WHERE oid='public.churches'::regclass) <> current_user THEN
    RAISE EXCEPTION 'Snapshot view must be provisioned by the verified source owner';
  END IF;
END $$;

-- NOLOGIN until separate approval, credential provisioning and allow/deny tests.
-- No application-role memberships, superuser, database/role creation or RLS bypass.
CREATE ROLE churchmap_analytics NOLOGIN NOINHERIT NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
CREATE ROLE churchmap_snapshot_reader NOLOGIN NOINHERIT NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1;
-- PG16+: creator ADMIN membership alone does not allow SET ROLE.
-- Temporarily enable SET, without inheritance; revoke SET before completion.
-- Retain the creator's ADMIN-only membership for later containment/removal.
GRANT churchmap_analytics TO CURRENT_USER WITH INHERIT FALSE, SET TRUE;
CREATE SCHEMA raw AUTHORIZATION churchmap_analytics;
CREATE SCHEMA analytics AUTHORIZATION churchmap_analytics;
CREATE SCHEMA analytics_seeds AUTHORIZATION churchmap_analytics;
-- SET permission is not inherited ownership: run owner ACL changes explicitly.
SET LOCAL ROLE churchmap_analytics;
REVOKE ALL ON SCHEMA raw, analytics, analytics_seeds
  FROM PUBLIC, anon, authenticated, service_role;

-- Global defaults are necessary: a schema-specific REVOKE cannot undo a
-- globally granted default function EXECUTE. Objects must be created as this role.
ALTER DEFAULT PRIVILEGES FOR ROLE churchmap_analytics
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE churchmap_analytics
  REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE churchmap_analytics
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE churchmap_analytics
  REVOKE USAGE ON TYPES FROM PUBLIC, anon, authenticated, service_role;
RESET ROLE;
ALTER ROLE churchmap_analytics SET search_path = pg_catalog, analytics;
ALTER ROLE churchmap_analytics SET statement_timeout = '120s';
ALTER ROLE churchmap_analytics SET lock_timeout = '3s';
ALTER ROLE churchmap_snapshot_reader SET search_path = pg_catalog;
ALTER ROLE churchmap_snapshot_reader SET default_transaction_read_only = on;
ALTER ROLE churchmap_snapshot_reader SET statement_timeout = '30s';
-- Admin-owned private view: the reader never receives raw google_address.
-- Keep this schema outside Data API and outside analytics role ownership.
CREATE SCHEMA churchmap_snapshot;
REVOKE ALL ON SCHEMA churchmap_snapshot FROM PUBLIC, anon, authenticated, service_role;
-- This view creates a production migration dependency. See README's
-- migration-window procedure before dropping/retyping referenced columns.
CREATE VIEW churchmap_snapshot.churches AS
SELECT church_id,name,address,city,state,zip_code,latitude,longitude,
       website,phone,source,external_id,denomination,
       coalesce(btrim(google_address) <> '', false) AS has_google_address
FROM public.churches;
REVOKE ALL ON churchmap_snapshot.churches
  FROM PUBLIC, anon, authenticated, service_role, churchmap_analytics;
GRANT USAGE ON SCHEMA churchmap_snapshot TO churchmap_snapshot_reader;
GRANT SELECT ON churchmap_snapshot.churches TO churchmap_snapshot_reader;
-- View access uses its administrator owner's base-table/RLS permissions.
-- Do not switch to security_invoker or add a broad reader RLS policy.

-- Stop if PUBLIC/inherited privileges would defeat the new role boundary.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog','information_schema',
      'raw','analytics','analytics_seeds','churchmap_snapshot')
      AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','f')
  LOOP
    IF has_table_privilege('churchmap_analytics',r.oid,'INSERT,UPDATE,DELETE,TRUNCATE')
       OR has_table_privilege('churchmap_snapshot_reader',r.oid,'INSERT,UPDATE,DELETE,TRUNCATE')
       OR has_any_column_privilege('churchmap_analytics',r.oid,'INSERT,UPDATE')
       OR has_any_column_privilege('churchmap_snapshot_reader',r.oid,'INSERT,UPDATE') THEN
      RAISE EXCEPTION 'Production write grant is inherited; review PUBLIC ACLs';
    END IF;
  END LOOP;
  -- Application relations only: extension monitoring views in other schemas
  -- can legitimately grant PUBLIC SELECT. Review new application schemas here.
  FOR r IN
    SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
  LOOP
    IF has_table_privilege('churchmap_snapshot_reader',r.oid,'SELECT')
       OR has_any_column_privilege('churchmap_snapshot_reader',r.oid,'SELECT')
       OR has_table_privilege('churchmap_analytics',r.oid,'SELECT')
       OR has_any_column_privilege('churchmap_analytics',r.oid,'SELECT') THEN
      RAISE EXCEPTION 'Application SELECT bypasses private view; review inherited grants';
    END IF;
  END LOOP;
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE c.relkind='S' AND n.nspname NOT IN
      ('pg_catalog','information_schema','raw','analytics','analytics_seeds')
      AND (has_sequence_privilege('churchmap_analytics',c.oid,'USAGE,UPDATE')
        OR has_sequence_privilege('churchmap_snapshot_reader',c.oid,'USAGE,UPDATE'))
  ) THEN
    RAISE EXCEPTION 'Inherited sequence mutation privileges need review';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname NOT IN ('pg_catalog','information_schema')
      AND p.prosecdef AND
      ((has_schema_privilege('churchmap_analytics',n.oid,'USAGE') AND
        has_function_privilege('churchmap_analytics',p.oid,'EXECUTE')) OR
       (has_schema_privilege('churchmap_snapshot_reader',n.oid,'USAGE') AND
        has_function_privilege('churchmap_snapshot_reader',p.oid,'EXECUTE')))
  ) THEN
    RAISE EXCEPTION 'Callable SECURITY DEFINER function needs review';
  END IF;
END $$;
REVOKE SET OPTION FOR churchmap_analytics FROM CURRENT_USER;
-- Auto-created memberships may have a different grantor. A new GRANT cannot
-- normalize them, and the REVOKE above affects only its own grantor's row.
-- Fail closed on e.g. createrole_self_grant='set,inherit'; do not alter that
-- server configuration or another grantor's memberships as incidental cleanup.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_auth_members m
    JOIN pg_roles target ON target.oid=m.roleid
    JOIN pg_roles member_role ON member_role.oid=m.member
    WHERE member_role.rolname=current_user
      AND target.rolname IN ('churchmap_analytics','churchmap_snapshot_reader')
      AND (m.set_option OR m.inherit_option)
  ) THEN
    RAISE EXCEPTION 'Provisioner retains SET/INHERIT through a membership grantor';
  END IF;
END $$;
-- No credentials, LOGIN, database-wide grants or publisher role in this draft.
ROLLBACK;
