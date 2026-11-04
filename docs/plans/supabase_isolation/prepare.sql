-- REVIEW DRAFT. NOT EXECUTED. Default ROLLBACK; not a runtime migration.
-- Before authorized application: save current ACLs; confirm runtime identity,
-- Data API exposure, no schema/role collisions, and database CREATE privilege.
-- Run as an authorized provisioning administrator, never the runtime app.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN
    ('churchmap_analytics','churchmap_snapshot_reader')) THEN
    RAISE EXCEPTION 'Proposed roles already exist; inspect instead of reusing';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname IN
    ('raw','analytics','analytics_seeds')) THEN
    RAISE EXCEPTION 'Proposed schemas already exist; inspect instead of reusing';
  END IF;
  IF to_regclass('public.churches') IS NULL THEN
    RAISE EXCEPTION 'Expected source table missing';
  END IF;
END $$;

-- NOLOGIN until separate approval, credential provisioning and allow/deny tests.
-- No role memberships, superuser, database creation, role creation or RLS bypass.
CREATE ROLE churchmap_analytics NOLOGIN NOINHERIT NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
CREATE ROLE churchmap_snapshot_reader NOLOGIN NOINHERIT NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1;
CREATE SCHEMA raw AUTHORIZATION churchmap_analytics;
CREATE SCHEMA analytics AUTHORIZATION churchmap_analytics;
CREATE SCHEMA analytics_seeds AUTHORIZATION churchmap_analytics;
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
ALTER ROLE churchmap_analytics SET search_path = analytics, pg_catalog;
ALTER ROLE churchmap_analytics SET statement_timeout = '120s';
ALTER ROLE churchmap_analytics SET lock_timeout = '3s';
ALTER ROLE churchmap_snapshot_reader SET search_path = pg_catalog;
ALTER ROLE churchmap_snapshot_reader SET default_transaction_read_only = on;
ALTER ROLE churchmap_snapshot_reader SET statement_timeout = '30s';
GRANT USAGE ON SCHEMA public TO churchmap_snapshot_reader;
-- Same source columns as load_snapshot.py. google_address is used only to
-- derive has_google_address; no users/reviews or whole-table SELECT granted.
GRANT SELECT (church_id,name,address,city,state,zip_code,latitude,longitude,
  website,phone,source,external_id,denomination,google_address)
  ON public.churches TO churchmap_snapshot_reader;

-- Stop if PUBLIC/inherited privileges would defeat the new role boundary.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
  LOOP
    IF has_table_privilege('churchmap_analytics',r.oid,'INSERT,UPDATE,DELETE,TRUNCATE')
       OR has_table_privilege('churchmap_snapshot_reader',r.oid,'INSERT,UPDATE,DELETE,TRUNCATE')
       OR has_any_column_privilege('churchmap_analytics',r.oid,'INSERT,UPDATE')
       OR has_any_column_privilege('churchmap_snapshot_reader',r.oid,'INSERT,UPDATE') THEN
      RAISE EXCEPTION 'Production write grant is inherited; review PUBLIC ACLs';
    END IF;
  END LOOP;
  IF EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='public' AND p.prosecdef AND
      (has_function_privilege('churchmap_analytics',p.oid,'EXECUTE') OR
       has_function_privilege('churchmap_snapshot_reader',p.oid,'EXECUTE'))
  ) THEN
    RAISE EXCEPTION 'Callable public SECURITY DEFINER function needs review';
  END IF;
END $$;
-- No credentials, LOGIN, database-wide grants or publisher role in this draft.
ROLLBACK;
