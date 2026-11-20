-- Close the Supabase Data API to the ten public tables the security advisor
-- reports with RLS disabled. Nothing in this app reaches them that way: the
-- API, crawler and migration runner connect as the table owner (postgres),
-- and no Supabase client, anon key or /rest/v1 call exists in the code. Yet
-- the anon and authenticated roles still hold full grants on them, so anyone
-- with the public anon key could read users and reviews, or truncate them.
--
-- Two layers, no policies:
--   1. RLS on. The owner bypasses RLS that is not FORCEd, so the app is
--      unaffected; any other role with a grant sees no rows.
--   2. Grants from anon and authenticated revoked, plus the default privileges
--      that would grant them on the next table postgres creates.
--
-- churches, church_fact_sources and publish_log already have RLS and the
-- churchmap_publisher policies (docs/plans/publisher_role); they are left as
-- they are. service_role, churchmap_publisher, churchmap_analytics and
-- churchmap_snapshot_reader grants are not touched.
--
-- On plain Postgres (tests, local dev) anon and authenticated do not exist,
-- so only step 1 runs there. Under Supabase this runs as postgres; if it does
-- not, ALTER DEFAULT PRIVILEGES fails and the whole migration rolls back.
--
-- ENABLE ROW LEVEL SECURITY takes an ACCESS EXCLUSIVE lock on each table.
-- Give up after 10 s rather than queue live reads behind a long crawl
-- transaction; the deploy then fails and can simply be retried.
SET LOCAL lock_timeout = '10s';

DO $$
DECLARE
    t text;
    tables text[] := ARRAY[
        'api_usage', 'church_embeddings', 'church_program_extractions',
        'church_programs', 'crawl_runs', 'raw_crawl_artifacts', 'reviews',
        'robots_cache', 'schema_migrations', 'users'];
    supabase_roles boolean := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
                          AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated');
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        IF supabase_roles THEN
            EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', t);
        END IF;
    END LOOP;

    IF supabase_roles THEN
        ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
            REVOKE ALL ON TABLES FROM anon, authenticated;

        -- A grant made by another grantor, to PUBLIC, or on a column survives
        -- the REVOKE above. Fail the migration rather than report it done.
        FOREACH t IN ARRAY tables LOOP
            IF has_table_privilege('anon', 'public.' || quote_ident(t),
                       'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR has_table_privilege('authenticated', 'public.' || quote_ident(t),
                       'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR has_any_column_privilege('anon', 'public.' || quote_ident(t),
                       'SELECT,INSERT,UPDATE,REFERENCES')
               OR has_any_column_privilege('authenticated', 'public.' || quote_ident(t),
                       'SELECT,INSERT,UPDATE,REFERENCES') THEN
                RAISE EXCEPTION 'anon or authenticated still has a privilege on public.%', t;
            END IF;
        END LOOP;
    END IF;
END
$$;
