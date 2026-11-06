-- REVIEW DRAFT ONLY. No production execution. Default ROLLBACK.
-- Owner approved churches DELETE on 2026-11-06 to preserve inserted-row revert.
BEGIN;
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
DO $$
BEGIN
  IF current_setting('server_version_num')::int < 170000 THEN
    RAISE EXCEPTION 'Validate on the production PostgreSQL major first';
  END IF;
  IF EXISTS (SELECT FROM pg_roles WHERE rolname='churchmap_publisher') THEN
    RAISE EXCEPTION 'Role already exists; inspect instead of reusing';
  END IF;
  IF EXISTS (SELECT FROM pg_class WHERE oid IN
      ('public.churches'::regclass, 'public.church_fact_sources'::regclass,
       'public.publish_log'::regclass) AND (relrowsecurity OR relforcerowsecurity)) THEN
    RAISE EXCEPTION 'RLS requires owner review; do not bypass';
  END IF;
END $$;
CREATE ROLE churchmap_publisher NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB
  NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
ALTER ROLE churchmap_publisher SET search_path = pg_catalog, public;
ALTER ROLE churchmap_publisher SET statement_timeout = '60s';
GRANT USAGE ON SCHEMA public TO churchmap_publisher;
GRANT SELECT, INSERT, DELETE ON public.churches TO churchmap_publisher;
GRANT UPDATE (name, denomination, address, city, state, zip_code, phone,
  service_times, service_languages, kids_program, website, facebook_url,
  latitude, longitude, scope_status, display_tradition, verified_at, verified_by)
  ON public.churches TO churchmap_publisher;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.church_fact_sources TO churchmap_publisher;
GRANT SELECT, INSERT ON public.publish_log TO churchmap_publisher;
DO $$
DECLARE seq text; obj record;
BEGIN
  FOREACH seq IN ARRAY ARRAY[
    pg_get_serial_sequence('public.churches','church_id'),
    pg_get_serial_sequence('public.publish_log','id')]
  LOOP
    IF seq IS NOT NULL THEN
      EXECUTE format('GRANT USAGE ON SEQUENCE %s TO churchmap_publisher', seq);
    END IF;
  END LOOP;
  -- NOINHERIT does not remove PUBLIC grants. Reject excessive effective access.
  IF has_database_privilege('churchmap_publisher',current_database(),'CREATE') THEN
    RAISE EXCEPTION 'Inherited database DDL privilege';
  END IF;
  FOR obj IN SELECT oid FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname <> 'information_schema'
  LOOP
    IF has_schema_privilege('churchmap_publisher',obj.oid,'CREATE') THEN
      RAISE EXCEPTION 'Inherited schema DDL privilege';
    END IF;
  END LOOP;
  FOR obj IN SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f') AND c.oid NOT IN
      ('public.churches'::regclass,'public.church_fact_sources'::regclass,'public.publish_log'::regclass)
  LOOP
    IF has_table_privilege('churchmap_publisher',obj.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
       OR has_any_column_privilege('churchmap_publisher',obj.oid,'SELECT,INSERT,UPDATE,REFERENCES') THEN
      RAISE EXCEPTION 'Inherited unrelated application privilege';
    END IF;
  END LOOP;
  IF has_table_privilege('churchmap_publisher','public.churches','UPDATE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_table_privilege('churchmap_publisher','public.publish_log','UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_table_privilege('churchmap_publisher','public.church_fact_sources','TRUNCATE,REFERENCES,TRIGGER') THEN
    RAISE EXCEPTION 'Inherited privileges exceed publisher contract';
  END IF;
  FOR obj IN SELECT a.attname FROM pg_attribute a WHERE a.attrelid='public.churches'::regclass
    AND a.attnum > 0 AND NOT a.attisdropped AND a.attname NOT IN
    ('name','denomination','address','city','state','zip_code','phone','service_times',
     'service_languages','kids_program','website','facebook_url','latitude','longitude',
     'scope_status','display_tradition','verified_at','verified_by')
  LOOP
    IF has_column_privilege('churchmap_publisher','public.churches',obj.attname,'UPDATE') THEN
      RAISE EXCEPTION 'Inherited non-publisher column update privilege';
    END IF;
  END LOOP;
  IF EXISTS (SELECT FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='churchmap_publisher')) THEN
    RAISE EXCEPTION 'Publisher must have no role memberships';
  END IF;
END $$;
ROLLBACK;
