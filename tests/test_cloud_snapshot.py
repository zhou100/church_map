"""Pure gates + real SQL behavior on an explicitly identified loopback test DB."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from analytics.scripts import cloud_snapshot as s
from analytics.scripts import cloud_dbt as d


def snap(n=10):
    return s.Snapshot(tuple((i, 'fixture', *([None] * 11), False) for i in range(n)),
                      'source-fixture', datetime.now(timezone.utc), 'a' * 64, n * 100)


def baseline(x):
    return {'identity': x.identity, 'scope': x.scope, 'expected_rows': len(x.rows)}


def previous(x, count=10):
    return (x.identity, x.scope, count, x.taken_at - timedelta(seconds=1))


def test_count_boundary_and_growth():
    x = snap(8)
    s.validate_count(x, previous(x))  # exactly 20% drop accepted
    s.validate_count(snap(15), previous(x))
    with pytest.raises(s.GateError, match='count_drop'):
        s.validate_count(snap(7), previous(x))


@pytest.mark.parametrize('change,error', [({'identity': 'other'}, 'source_scope'),
                                         ({'scope': 'CA'}, 'source_scope'),
                                         ({'taken_at': datetime(2000,1,1,tzinfo=timezone.utc)}, 'stale')])
def test_identity_scope_and_delayed_result(change, error):
    x = snap()
    with pytest.raises(s.GateError, match=error):
        s.validate_count(replace(x, **change), previous(x))


def test_first_load_needs_independent_exact_baseline():
    x = snap()
    for b in (None, {}, {**baseline(x), 'expected_rows': 9}):
        with pytest.raises(s.GateError):
            s.validate_count(x, None, b)
    s.validate_count(x, None, baseline(x))
    with pytest.raises(s.GateError, match='empty'):
        s.validate_count(snap(0), None, baseline(snap(0)))


def test_cloud_profile_mapping_and_session_only():
    env = d.cloud_env('postgresql://churchmap_analytics.project:fixture@db.example:5432/postgres')
    assert env['ANALYTICS_CLOUD_PGUSER'] == 'churchmap_analytics.project'
    for url in ['postgresql://postgres:fixture@db.example/postgres',
                'postgresql://churchmap_analytics:fixture@db.example:6543/postgres']:
        with pytest.raises(s.GateError):
            d.cloud_env(url)
    profile = Path('analytics/dbt/profiles.yml').read_text().split('    cloud:',1)[1]
    assert 'threads: 1' in profile and 'sslmode: require' in profile


def test_failure_output_never_echoes_client_or_credential(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv('PROD_READONLY_DATABASE_URL', 'private')
    def fail(url):
        print('PRIVATE PHONE AND NOTES')
        raise RuntimeError('PRIVATE PASSWORD AND URL')
    monkeypatch.setattr(s, 'capture', fail)
    assert s.main(['--report', str(tmp_path/'private.json')]) == 1
    out = capsys.readouterr()
    assert out.err == '' and out.out == '{"step":"cloud_snapshot","status":"failed"}\n'


def test_inspection_does_not_connect_target(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv('PROD_READONLY_DATABASE_URL', 'private')
    monkeypatch.setattr(s, 'capture', lambda _: snap())
    monkeypatch.setattr(s, 'connect', lambda _: pytest.fail('target connection in inspect'))
    report = tmp_path/'report.json'
    assert s.main(['--report', str(report)]) == 0
    assert json.loads(report.read_text())['applied'] is False
    assert report.stat().st_mode & 0o777 == 0o600
    assert 'fixture' not in capsys.readouterr().out
    assert s.main(['--report', str(report)]) == 1  # never overwrite


@pytest.fixture(scope='module')
def db():
    url = os.environ.get('DATABASE_URL')
    if not url:
        pytest.skip('isolated Postgres DATABASE_URL required')
    info = conninfo_to_dict(url)
    if info.get('host') not in {'127.0.0.1','localhost','::1'} or not info.get('dbname','').endswith('_test') and info.get('dbname') != 'churchmap_test':
        pytest.fail('refusing non-loopback/non-test database')
    admin = psycopg.connect(url, autocommit=True)
    assert admin.execute('SELECT current_database()').fetchone()[0] == info['dbname']
    roles = ('churchmap_analytics','churchmap_snapshot_reader')
    for role in roles:
        assert not admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone(), 'test role collision'
        admin.execute(psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'fixture-only' NOSUPERUSER NOBYPASSRLS").format(psycopg.sql.Identifier(role)))
    admin.execute('CREATE SCHEMA raw AUTHORIZATION churchmap_analytics')
    admin.execute('CREATE SCHEMA churchmap_snapshot')
    admin.execute('CREATE TABLE churchmap_snapshot.fixture (' + ','.join(
        ["church_id bigint", *[f'{n} text' for n in s.FIELDS[1:6]],
         'latitude double precision','longitude double precision',
         *[f'{n} text' for n in s.FIELDS[8:-1]],'has_google_address boolean']) + ')')
    admin.execute('CREATE VIEW churchmap_snapshot.churches AS SELECT * FROM churchmap_snapshot.fixture')
    admin.execute('GRANT USAGE ON SCHEMA churchmap_snapshot TO churchmap_snapshot_reader')
    admin.execute('GRANT SELECT ON churchmap_snapshot.churches TO churchmap_snapshot_reader')
    urls = {r: make_conninfo(url, user=r, password='fixture-only') for r in roles}
    yield admin, urls
    # Only synthetic schemas/roles this module created, in a verified test DB.
    admin.execute('DROP SCHEMA raw CASCADE; DROP SCHEMA churchmap_snapshot CASCADE')
    for role in roles:
        admin.execute(psycopg.sql.SQL('DROP ROLE {}').format(psycopg.sql.Identifier(role)))
    admin.close()


@pytest.fixture
def fresh(db):
    admin, urls = db
    admin.execute('TRUNCATE churchmap_snapshot.fixture')
    admin.execute("INSERT INTO churchmap_snapshot.fixture(church_id,name,has_google_address) SELECT n,'synthetic',false FROM generate_series(1,10) n")
    admin.execute('DROP SCHEMA raw CASCADE; CREATE SCHEMA raw AUTHORIZATION churchmap_analytics')
    return admin, urls


def evidence(con):
    return {'database_identity': s.database_identity(con),
            'observed_at': datetime.now(timezone.utc).isoformat(), 'disk_free_bytes': 1_000_000_000}


def apply(url, x, b=None):
    with s.connect(url) as con:
        s.install(con, x, b, evidence(con))


def test_real_capture_and_atomic_replacement_preserves_views(fresh):
    admin, urls = fresh
    x = s.capture(urls['churchmap_snapshot_reader'])
    assert len(x.rows) == 10 and all(r[-1] is False for r in x.rows)
    apply(urls['churchmap_analytics'], x, baseline(x))
    admin.execute('CREATE VIEW raw.consumer AS SELECT count(*) AS n FROM raw.churches')
    old_oid = admin.execute("SELECT 'raw.churches'::regclass::oid").fetchone()[0]
    admin.execute('DELETE FROM churchmap_snapshot.fixture WHERE church_id>8')
    new = s.capture(urls['churchmap_snapshot_reader'])
    apply(urls['churchmap_analytics'], new)
    assert admin.execute('SELECT n FROM raw.consumer').fetchone() == (8,)
    assert admin.execute("SELECT 'raw.churches'::regclass::oid").fetchone()[0] == old_oid
    assert admin.execute('SELECT snapshot_row_count,snapshot_sha256 FROM raw.snapshot_meta').fetchone() == (8,new.sha256)


def test_real_failure_keeps_prior_data_and_metadata(fresh):
    admin, urls = fresh
    x = s.capture(urls['churchmap_snapshot_reader']); apply(urls['churchmap_analytics'], x, baseline(x))
    before = admin.execute('SELECT * FROM raw.snapshot_meta').fetchall()
    broken = replace(x, taken_at=x.taken_at+timedelta(seconds=1), rows=x.rows+(x.rows[0],))
    with pytest.raises(psycopg.errors.UniqueViolation):
        apply(urls['churchmap_analytics'], broken)
    assert admin.execute('SELECT count(*) FROM raw.churches').fetchone() == (10,)
    assert admin.execute('SELECT * FROM raw.snapshot_meta').fetchall() == before
    with pytest.raises(s.GateError, match='stale'):
        apply(urls['churchmap_analytics'], x)


def test_real_empty_shape_and_count_drop(fresh):
    admin, urls = fresh
    x=s.capture(urls['churchmap_snapshot_reader']); apply(urls['churchmap_analytics'],x,baseline(x))
    admin.execute('DELETE FROM churchmap_snapshot.fixture WHERE church_id>7')
    with pytest.raises(s.GateError, match='count_drop'):
        apply(urls['churchmap_analytics'],s.capture(urls['churchmap_snapshot_reader']))
    admin.execute('TRUNCATE churchmap_snapshot.fixture')
    with pytest.raises(s.GateError, match='empty'):
        s.capture(urls['churchmap_snapshot_reader'])
    admin.execute("CREATE OR REPLACE VIEW churchmap_snapshot.churches AS SELECT *, 'private'::text AS google_address FROM churchmap_snapshot.fixture")
    with pytest.raises(s.GateError, match='shape'):
        s.capture(urls['churchmap_snapshot_reader'])
    admin.execute('DROP VIEW churchmap_snapshot.churches; CREATE VIEW churchmap_snapshot.churches AS SELECT * FROM churchmap_snapshot.fixture; GRANT SELECT ON churchmap_snapshot.churches TO churchmap_snapshot_reader')
    assert admin.execute('SELECT count(*) FROM raw.churches').fetchone() == (10,)


def test_real_concurrent_lock_and_capacity_refusal(fresh):
    admin, urls = fresh
    x=s.capture(urls['churchmap_snapshot_reader'])
    with s.connect(urls['churchmap_analytics']) as holder:
        holder.execute('SELECT pg_advisory_xact_lock(%s)',(s.LOCK_ID,))
        with pytest.raises(s.GateError,match='analytics_busy'):
            apply(urls['churchmap_analytics'],x,baseline(x))
    with s.connect(urls['churchmap_analytics']) as con:
        with pytest.raises(s.GateError,match='disk_evidence_required'):
            s.install(con,x,baseline(x),None)
    assert admin.execute("SELECT to_regclass('raw.churches')").fetchone() == (None,)


def test_snapshot_repeatable_read_under_concurrent_source_change(fresh, monkeypatch):
    admin, urls = fresh
    admin.execute('TRUNCATE churchmap_snapshot.fixture')
    admin.execute("INSERT INTO churchmap_snapshot.fixture(church_id,name,has_google_address) SELECT n,'before',false FROM generate_series(1,1001) n")
    original = s.connect
    changed = []
    class Cursor:
        def __init__(self, cur): self.cur = cur
        def __enter__(self): self.cur.__enter__(); return self
        def __exit__(self, *args): return self.cur.__exit__(*args)
        def execute(self, *args): return self.cur.execute(*args)
        def fetchmany(self, n):
            batch = self.cur.fetchmany(n)
            if batch and not changed:
                admin.execute("UPDATE churchmap_snapshot.fixture SET name='after' WHERE church_id=1001")
                changed.append(True)
            return batch
    class Connection:
        def __init__(self,c): object.__setattr__(self,'c',c)
        def __getattr__(self,k): return getattr(self.c,k)
        def __setattr__(self,k,v): setattr(self.c,k,v)
        def __enter__(self): self.c.__enter__(); return self
        def __exit__(self,*args): return self.c.__exit__(*args)
        def cursor(self,**kw): return Cursor(self.c.cursor(**kw))
    monkeypatch.setattr(s,'connect',lambda url: Connection(original(url)))
    x=s.capture(urls['churchmap_snapshot_reader'])
    assert len(x.rows)==1001 and x.rows[-1][1]=='before'
    assert admin.execute('SELECT name FROM churchmap_snapshot.fixture WHERE church_id=1001').fetchone()==('after',)


def test_capacity_evidence_binding_and_age(fresh):
    _, urls = fresh
    with s.connect(urls['churchmap_analytics']) as c:
        e=evidence(c)
        s.capacity_gate(c,e)
        for bad,match in [({**e,'database_identity':'other'},'required'),
                          ({**e,'observed_at':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()},'stale'),
                          ({**e,'disk_free_bytes':1},'headroom')]:
            with pytest.raises(s.GateError,match=match):s.capacity_gate(c,bad)


def test_legacy_metadata_and_bad_baseline_preserve_previous_snapshot(fresh):
    admin, urls=fresh
    with s.connect(urls['churchmap_analytics']) as c:
        c.execute(s.MIGRATION.read_text(),prepare=False)
    admin.execute("INSERT INTO raw.churches(church_id,name) VALUES(99,'legacy')")
    admin.execute("INSERT INTO raw.snapshot_meta(snapshot_source,snapshot_taken_at,loaded_at) VALUES('sqlite:holyhub.db',now(),now())")
    x=s.capture(urls['churchmap_snapshot_reader'])
    with pytest.raises(s.GateError,match='baseline_required'):
        apply(urls['churchmap_analytics'],x)
    assert admin.execute('SELECT church_id FROM raw.churches').fetchall()==[(99,)]
    apply(urls['churchmap_analytics'],x,baseline(x))
    assert admin.execute('SELECT count(*) FROM raw.churches').fetchone()==(10,)


@pytest.mark.parametrize('returncode',[0,1])
def test_dbt_runner_private_logs_and_fixed_options(monkeypatch,tmp_path,capsys,returncode):
    from types import SimpleNamespace
    class Fake:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,q,args=None):return self
        def fetchone(self):return (True,)
        def fetchall(self):return [('identity',10,'snapshot_gate_v1')]
    monkeypatch.setenv('ANALYTICS_DATABASE_URL','postgresql://churchmap_analytics:private@db.example:5432/postgres')
    monkeypatch.setattr(d,'connect',lambda _:Fake())
    monkeypatch.setattr(d,'require_role',lambda *args:None)
    monkeypatch.setattr(d,'capacity_gate',lambda *args:None)
    evidence_path=tmp_path/'evidence.json';evidence_path.write_text('{}')
    def run(cmd,**kwargs):
        assert cmd[1:4]==['-m','dbt.cli.main','build']
        assert cmd[cmd.index('--target')+1]=='cloud'
        assert kwargs['timeout']==900
        print('PRIVATE PROVIDER ERROR')
        kwargs['stdout'].write('PRIVATE DBT DETAILS')
        return SimpleNamespace(returncode=returncode)
    monkeypatch.setattr(d.subprocess,'run',run)
    logdir=tmp_path/'private'
    result=d.main(['--capacity-evidence',str(evidence_path),'--private-dir',str(logdir)])
    assert result==(0 if returncode==0 else 1)
    out=capsys.readouterr()
    assert 'PRIVATE' not in out.out+out.err and out.err==''
    assert (logdir/'build.log').read_text()=='PRIVATE DBT DETAILS'
    assert logdir.stat().st_mode & 0o777==0o700


def test_gate_version_and_metadata_grain_fail_closed(fresh):
    admin, urls=fresh
    x=s.capture(urls['churchmap_snapshot_reader']);apply(urls['churchmap_analytics'],x,baseline(x))
    newer=replace(x,taken_at=x.taken_at+timedelta(seconds=1))
    admin.execute("UPDATE raw.snapshot_meta SET snapshot_gate_version='future_version'")
    with pytest.raises(s.GateError,match='gate_version_changed'):
        apply(urls['churchmap_analytics'],newer)
    admin.execute('INSERT INTO raw.snapshot_meta SELECT * FROM raw.snapshot_meta')
    with pytest.raises(s.GateError,match='metadata_grain'):
        apply(urls['churchmap_analytics'],newer)
    assert admin.execute('SELECT count(*) FROM raw.churches').fetchone()==(10,)
