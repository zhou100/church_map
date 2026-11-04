"""Synthetic PG17.6 isolation checks; use only the dedicated localhost fixture.

Requires a freshly initialized churchmap_isolation_test database and fixture
roles described in README.md. Does not accept production URLs or read env files.
Uses local COMMIT variants for rollback/recovery tests; tracked SQL stays ROLLBACK.
"""
import json
from pathlib import Path
import psycopg
ROOT=Path(__file__).resolve().parents[3]
SQLDIR=ROOT/'docs/plans/supabase_isolation'
DSN='host=127.0.0.1 port=55473 dbname=churchmap_isolation_test'
passed=[]
def conn(role='postgres'):
 c=psycopg.connect(DSN+' user='+role,autocommit=True)
 assert c.info.host=='127.0.0.1' and c.info.port==55473 and c.info.dbname=='churchmap_isolation_test'
 assert c.execute('SHOW server_version_num').fetchone()[0]=='170006'
 return c
def script(name,commit=False):
 s=(SQLDIR/name).read_text()
 return s.rsplit('ROLLBACK;',1)[0]+'COMMIT;' if commit else s
def run(name,commit=False):
 with conn() as c:c.execute(script(name,commit),prepare=False)
def expected_failure(name,sql,role='postgres',contains=None,code=None):
 try:
  with conn(role) as c:c.execute(sql,prepare=False)
 except psycopg.Error as e:
  if contains:assert contains in str(e),(name,str(e))
  if code:assert e.sqlstate==code,(name,e.sqlstate)
  passed.append(name);return
 raise AssertionError(name+' unexpectedly succeeded')
with conn('test_bootstrap') as c:
 assert c.execute("SELECT rolsuper FROM pg_roles WHERE rolname='postgres'").fetchone()==(False,)
with conn() as c:
 c.execute('CREATE TABLE public.churches(church_id bigint PRIMARY KEY,name text,address text,city text,state text,zip_code text,latitude float8,longitude float8,website text,phone text,source text,external_id text,denomination text,google_address text)')
 c.execute("INSERT INTO public.churches(church_id,name,google_address) VALUES(1,'Synthetic congregation','Synthetic address'),(2,'Synthetic blank','  ')")
 c.execute('CREATE TABLE public.users(id int); CREATE TABLE public.reviews(id int); CREATE TABLE public.publish_log(id int); CREATE TABLE public.church_fact_sources(id int)')
 c.execute('GRANT ALL ON ALL TABLES IN SCHEMA public TO anon,authenticated,service_role')
 c.execute('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon,authenticated,service_role')
run('prepare.sql');passed.append('prepare_as_non_superuser_default_rollback')
with conn() as c:assert c.execute("SELECT count(*) FROM pg_roles WHERE rolname='churchmap_analytics'").fetchone()==(0,)
for title,setup,cleanup,message in [
 ('inherited_users_select','GRANT SELECT ON public.users TO PUBLIC','REVOKE SELECT ON public.users FROM PUBLIC','Application SELECT'),
 ('inherited_column_select','GRANT SELECT(id) ON public.reviews TO PUBLIC','REVOKE SELECT(id) ON public.reviews FROM PUBLIC','Application SELECT'),
 ('inherited_write','GRANT INSERT ON public.users TO PUBLIC','REVOKE INSERT ON public.users FROM PUBLIC','Production write'),
 ('sequence_mutation','CREATE SEQUENCE public.guard_seq; GRANT UPDATE ON public.guard_seq TO PUBLIC','DROP SEQUENCE public.guard_seq','sequence mutation'),
 ('nonpublic_definer','CREATE SCHEMA extension_fixture; GRANT USAGE ON SCHEMA extension_fixture TO PUBLIC; CREATE FUNCTION extension_fixture.guard() RETURNS int LANGUAGE sql SECURITY DEFINER AS \'SELECT 1\'','DROP FUNCTION extension_fixture.guard(); DROP SCHEMA extension_fixture','SECURITY DEFINER')]:
 with conn() as c:c.execute(setup)
 expected_failure(title,script('prepare.sql'),contains=message)
 with conn() as c:c.execute(cleanup)
with conn() as c:c.execute("ALTER ROLE postgres SET createrole_self_grant='set,inherit'")
expected_failure('all_grantor_membership_guard',script('prepare.sql'),contains='retains SET/INHERIT')
with conn() as c:c.execute('ALTER ROLE postgres RESET createrole_self_grant')
run('prepare.sql',True);passed.append('prepare_commit_local_only')
with conn() as c:
 c.execute('ALTER ROLE churchmap_analytics LOGIN; ALTER ROLE churchmap_snapshot_reader LOGIN')
with conn('churchmap_snapshot_reader') as c:
 assert c.execute('SHOW default_transaction_read_only').fetchone()==('on',)
 assert c.execute('SELECT church_id,has_google_address FROM churchmap_snapshot.churches ORDER BY 1').fetchall()==[(1,True),(2,False)]
passed.append('real_reader_login_boolean_projection')
for role in ['churchmap_snapshot_reader','churchmap_analytics']:
 for table in ['churches','users','reviews']:
  expected_failure(role+'_denied_'+table,'SELECT * FROM public.'+table,role,code='42501')
expected_failure('reader_raw_address_denied','SELECT google_address FROM churchmap_snapshot.churches','churchmap_snapshot_reader',code='42703')
with conn('churchmap_analytics') as c:
 assert c.execute('SHOW search_path').fetchone()==('pg_catalog, analytics',)
 c.execute('CREATE TABLE analytics.fixture(id int); INSERT INTO analytics.fixture VALUES(1)')
passed.append('real_analytics_login_private_write')
expected_failure('anon_private_denied','SELECT * FROM analytics.fixture','anon',code='42501')
expected_failure('private_writer_public_ddl_denied','CREATE TABLE public.forbidden(id int)','churchmap_analytics',code='42501')
expected_failure('remove_populated_refused',script('remove_empty.sql',True),code='2BP01')
expected_failure('view_blocks_column_retype','ALTER TABLE public.churches ALTER COLUMN name TYPE varchar(500)',code='0A000')
with conn() as c:c.execute('ALTER TABLE public.churches ENABLE ROW LEVEL SECURITY')
with conn('churchmap_snapshot_reader') as c:assert c.execute('SELECT count(*) FROM churchmap_snapshot.churches').fetchone()==(2,)
passed.append('owner_view_survives_regular_rls')
run('capacity_gate.sql');passed.append('capacity_current_fixture_passes')
# Fixture-only replacement of used-size input; no production quota assumptions.
for size in [300000000,272000000]:
 s=script('capacity_gate.sql').replace('pg_database_size(current_database())',str(size))
 expected_failure('capacity_boundary_'+str(size),s,contains='capacity gate failed')
run('contain.sql',True)
with conn() as c:
 assert c.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('churchmap_analytics','churchmap_snapshot_reader') AND rolcanlogin").fetchone()==(0,)
passed.append('contain_preserves_objects_disables_login')
with conn('test_bootstrap') as c:c.execute('DROP TABLE analytics.fixture')
run('remove_empty.sql',True);passed.append('remove_empty_as_non_superuser')
with conn() as c:
 assert c.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('churchmap_analytics','churchmap_snapshot_reader')").fetchone()==(0,)
print(json.dumps({'passed':len(passed),'checks':passed}))
