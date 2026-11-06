"""Synthetic PG17 real-login validation; hardcoded isolated loopback fixture only.

Requires migrations 0001–0006 in churchmap_publisher_test at port 55493.
Never loads environment files or accepts a production DSN. Fresh roles required.
"""
from pathlib import Path
import sys

import psycopg

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts import publish_verified as publisher

DSN = 'host=127.0.0.1 port=55493 dbname=churchmap_publisher_test'


def connect(role):
    con = psycopg.connect(DSN + ' user=' + role, autocommit=True, prepare_threshold=None)
    assert con.info.host == '127.0.0.1' and con.info.port == 55493
    assert con.info.dbname == 'churchmap_publisher_test'
    assert int(con.execute('SHOW server_version_num').fetchone()[0]) // 10000 == 17
    return con


def denied(con, sql):
    try:
        con.execute(sql)
    except psycopg.errors.InsufficientPrivilege:
        return
    raise AssertionError('forbidden statement succeeded')


def main():
    sql = (Path(__file__).with_name('prepare.sql')).read_text()
    with connect('test_bootstrap') as admin:
        admin.execute('CREATE ROLE postgres LOGIN NOSUPERUSER CREATEROLE CREATEDB NOBYPASSRLS')
        admin.execute('CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS')
        admin.execute('GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role')
        admin.execute('GRANT ALL ON ALL TABLES IN SCHEMA public TO postgres WITH GRANT OPTION')
        admin.execute('GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO postgres WITH GRANT OPTION')
        # Fixtures emulate explicit Supabase grants without assigning API memberships.
        admin.execute('CREATE SCHEMA churchmap_snapshot')
        admin.execute('CREATE VIEW churchmap_snapshot.churches AS SELECT church_id,name,address FROM public.churches')
        admin.execute('GRANT USAGE ON SCHEMA public TO postgres WITH GRANT OPTION')
    with connect('postgres') as admin:
        admin.execute(sql, prepare=False)  # default rollback creates no role
        assert not admin.execute("SELECT 1 FROM pg_roles WHERE rolname='churchmap_publisher'").fetchone()
        admin.execute(sql.rsplit('ROLLBACK;', 1)[0] + 'COMMIT;', prepare=False)
        admin.execute('ALTER ROLE churchmap_publisher LOGIN')
    with connect('churchmap_publisher') as con:
        assert con.execute('SELECT current_user, session_user').fetchone() == ('churchmap_publisher',) * 2
        publisher.check_schema(con)
        inserted = publisher.build_plan(con, [], [{'external_id': 'publisher-fixture', 'name': 'Fixture',
            'address': '1 Fixture Street', 'address_source_url': 'https://example.org',
            'address_source_type': 'own_site'}])
        assert publisher.apply(con, inserted, 'fixture-insert') == {'inserted': 1}
        assert publisher.build_plan(con, [], [inserted[0]['row']]) == []
        church_id = con.execute("SELECT church_id FROM churches WHERE external_id='publisher-fixture'").fetchone()[0]
        update = publisher.build_plan(con, [{'church_id': church_id, 'phone': '6505550100'}], [])
        assert publisher.apply(con, update, 'fixture-update') == {'updated': 1}
        assert publisher.revert(con, 'fixture-update') == {'restored': 1}
        assert con.execute('SELECT phone FROM churches WHERE church_id=%s', (church_id,)).fetchone() == (None,)
        for statement in ["UPDATE churches SET source='other'", 'UPDATE churches SET church_id=church_id',
                          'DELETE FROM publish_log', 'UPDATE publish_log SET action=action',
                          'SELECT * FROM users', 'DELETE FROM reviews', 'CREATE TABLE public.forbidden(id int)',
                          'CREATE SCHEMA forbidden', 'ALTER TABLE churches ADD COLUMN forbidden int',
                          'SET ROLE service_role']:
            denied(con, statement)
        assert publisher.revert(con, 'fixture-insert') == {'deleted': 1}
        assert not con.execute('SELECT 1 FROM churches WHERE church_id=%s', (church_id,)).fetchone()
        assert not con.execute('SELECT 1 FROM church_fact_sources WHERE church_id=%s', (church_id,)).fetchone()
    print('passed: real login, dry run, apply, idempotency, update revert, denied privileges')
    print('passed: inserted-church revert and fact-source deletion')


if __name__ == '__main__':
    main()
