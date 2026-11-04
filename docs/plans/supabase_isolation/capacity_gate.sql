-- NOT EXECUTED. Read-only abort gate, before BOTH snapshot load and dbt build.
-- Runner must stop on any error (psql -v ON_ERROR_STOP=1); never just log it.
-- Conservative proposed limits in bytes, not a provider quota guarantee.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '15s';
DO $$
DECLARE
  used bigint := pg_database_size(current_database());
  rebuilt bigint;
  growth_budget bigint;
BEGIN
  SELECT coalesce(sum(pg_total_relation_size(c.oid)),0) INTO rebuilt
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname IN ('raw','analytics','analytics_seeds')
    AND c.relkind IN ('r','m');
  -- At least 128 MB incremental budget; increase with measured rebuild footprint.
  -- Includes initial loading reserve; input growth must be re-estimated separately.
  growth_budget := greatest(128000000::bigint, 2 * rebuilt);
  IF used >= 300000000 OR used + growth_budget >= 400000000 THEN
    RAISE EXCEPTION 'Shared database capacity gate failed; no load/build permitted';
  END IF;
END $$;
-- This does NOT measure filesystem free space/WAL, concurrent production growth,
-- or guarantee the peak estimate. Require current disk/WAL headroom observation
-- and a single analytics writer before each stage; missing evidence blocks it.
ROLLBACK;
