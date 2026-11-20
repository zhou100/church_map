"""Migration 0008 closes the Supabase Data API roles out of ten public tables.

Plain Postgres has no anon/authenticated roles, so the migration run by the
real runner only turns RLS on. The Supabase case is reproduced in one
rolled-back transaction: fixture roles with Supabase-style grants and default
privileges, then the migration SQL itself.
"""
import os
import re
from pathlib import Path

import psycopg
import pytest

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "0008_lock_down_public_tables.sql"
LOCKED = ['api_usage', 'church_embeddings', 'church_program_extractions', 'church_programs',
          'crawl_runs', 'raw_crawl_artifacts', 'reviews', 'robots_cache', 'schema_migrations', 'users']
# Already RLS-protected with churchmap_publisher policies (PR #84); 0008 must not touch them.
UNTOUCHED = ['churches', 'church_fact_sources', 'publish_log']
PRIVILEGES = 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'


def test_migration_names_exactly_the_ten_tables():
    sql = MIGRATION.read_text()
    listed = re.search(r"ARRAY\[(.*?)\]", sql, re.S).group(1)
    assert sorted(re.findall(r"'(\w+)'", listed)) == sorted(LOCKED)
    for table in UNTOUCHED:
        assert not re.search(rf"\b{table}\b", listed)


@pytest.fixture
def con():
    if not os.environ.get('DATABASE_URL'):
        pytest.skip('isolated Postgres DATABASE_URL required')
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        yield c
        c.rollback()


def rls(con, table):
    return con.execute("SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass",
                       (f'public.{table}',)).fetchone()[0]


def test_runner_applied_rls_to_the_ten_tables(con):
    assert con.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (MIGRATION.stem,)).fetchone()
    assert [t for t in LOCKED if not rls(con, t)] == []


def supabase_fixture(con):
    if con.execute("SELECT 1 FROM pg_roles WHERE rolname IN ('anon', 'authenticated')").fetchone():
        pytest.skip('anon/authenticated already exist in this cluster; fixture needs fresh roles')
    if not con.execute("SELECT pg_has_role(current_user, 'postgres', 'MEMBER') "
                       "FROM pg_roles WHERE rolname = 'postgres'").fetchone():
        pytest.skip('migration runs as postgres under Supabase; test needs that role')
    # As found in production on 2026-11-20: RLS off, full grants, Supabase default privileges.
    con.execute('CREATE ROLE anon NOLOGIN')
    con.execute('CREATE ROLE authenticated NOLOGIN')
    con.execute('GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated')
    con.execute('ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public '
                'GRANT ALL ON TABLES TO anon, authenticated')
    for table in LOCKED:
        con.execute(f'ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY')


def test_supabase_roles_lose_every_privilege_and_owner_keeps_access(con):
    supabase_fixture(con)
    before = {t: rls(con, t) for t in UNTOUCHED}
    con.execute(MIGRATION.read_text())

    for role in ('anon', 'authenticated'):
        for table in LOCKED:
            assert rls(con, table)
            assert not con.execute('SELECT has_table_privilege(%s, %s, %s)',
                                   (role, f'public.{table}', PRIVILEGES)).fetchone()[0], (role, table)
        # The three publisher tables keep their grants and RLS state: not in scope.
        for table in UNTOUCHED:
            assert con.execute('SELECT has_table_privilege(%s, %s, %s)',
                               (role, f'public.{table}', 'SELECT')).fetchone()[0], (role, table)
    assert {t: rls(con, t) for t in UNTOUCHED} == before

    # The next table postgres creates is not granted to them by default.
    con.execute('SET LOCAL ROLE postgres')
    con.execute('CREATE TABLE public.rls_lockdown_fixture (id int)')
    con.execute('RESET ROLE')
    assert not con.execute("SELECT has_table_privilege('anon', 'public.rls_lockdown_fixture', 'SELECT')").fetchone()[0]

    # The owner (the app's role) is not subject to non-forced RLS.
    con.execute('SET LOCAL ROLE postgres')
    con.execute("INSERT INTO users (google_id, email) VALUES ('rls-fixture', 'fixture@example.org')")
    assert con.execute("SELECT count(*) FROM users WHERE google_id = 'rls-fixture'").fetchone()[0] == 1
    con.execute('RESET ROLE')


def test_a_surviving_public_grant_fails_the_migration(con):
    supabase_fixture(con)
    con.execute('GRANT SELECT ON public.reviews TO PUBLIC')
    with pytest.raises(psycopg.errors.RaiseException, match='public.reviews'):
        with con.transaction():
            con.execute(MIGRATION.read_text())
