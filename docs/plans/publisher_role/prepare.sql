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
  -- Production has RLS enabled on all three tables with no policies (owner query,
  -- 2026-11-06). The publisher gets its own policies below; never BYPASSRLS. A
  -- policy for PUBLIC would also apply to the publisher, so stop if one exists.
  -- The policies below narrow table-wide INSERT/DELETE grants only while RLS is
  -- enabled; CREATE POLICY does not enable it. Never enable it here for others.
  IF EXISTS (SELECT FROM pg_class WHERE oid IN
      ('public.churches'::regclass, 'public.church_fact_sources'::regclass,
       'public.publish_log'::regclass) AND NOT relrowsecurity) THEN
    RAISE EXCEPTION 'RLS must be enabled on every publisher table; the policies would not apply';
  END IF;
  -- CREATE POLICY needs table ownership (Supabase's postgres is not superuser).
  IF EXISTS (SELECT FROM pg_class WHERE oid IN
      ('public.churches'::regclass, 'public.church_fact_sources'::regclass,
       'public.publish_log'::regclass) AND NOT pg_has_role(current_user, relowner, 'USAGE')) THEN
    RAISE EXCEPTION 'Run as the owner of the publisher tables';
  END IF;
  IF EXISTS (SELECT FROM pg_policies WHERE schemaname='public'
      AND tablename IN ('churches','church_fact_sources','publish_log')
      AND 'public' = ANY(roles)) THEN
    RAISE EXCEPTION 'A PUBLIC policy exists on a publisher table; review it first';
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
-- Row-level policies for this role only; anon/authenticated/other roles are untouched.
-- They narrow the grants: the publisher inserts and deletes only rows it owns
-- (source = 'muse'), so even a leaked credential cannot add or remove directory
-- churches. Without a SELECT policy, RLS would return zero rows silently and the
-- dry run would plan every published congregation as a new insert.
CREATE POLICY churchmap_publisher_select ON public.churches
  FOR SELECT TO churchmap_publisher USING (true);
CREATE POLICY churchmap_publisher_insert ON public.churches
  FOR INSERT TO churchmap_publisher WITH CHECK (source = 'muse');
CREATE POLICY churchmap_publisher_update ON public.churches
  FOR UPDATE TO churchmap_publisher USING (true) WITH CHECK (true);
CREATE POLICY churchmap_publisher_delete ON public.churches
  FOR DELETE TO churchmap_publisher USING (source = 'muse');
CREATE POLICY churchmap_publisher_all ON public.church_fact_sources
  FOR ALL TO churchmap_publisher USING (true) WITH CHECK (true);
CREATE POLICY churchmap_publisher_select ON public.publish_log
  FOR SELECT TO churchmap_publisher USING (true);
CREATE POLICY churchmap_publisher_insert ON public.publish_log
  FOR INSERT TO churchmap_publisher WITH CHECK (true);
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
  IF (SELECT count(*) FROM pg_policies WHERE schemaname='public'
      AND 'churchmap_publisher' = ANY(roles)) <> 7 THEN
    RAISE EXCEPTION 'Publisher policies incomplete';
  END IF;
END $$;
ROLLBACK;
