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
from analytics.scripts import snapshot_state as state
from botocore.exceptions import ClientError
import hashlib
from io import BytesIO
import uuid


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


def test_job_target_and_secret_isolation(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'production-secret')
    monkeypatch.setenv('R2_SECRET_ACCESS_KEY', 'private')
    monkeypatch.setenv('PGHOSTADDR', '203.0.113.1')
    env = d.job_env('postgresql://job:fixture@127.0.0.1:5432/churchmap_run_abcdef12')
    assert env['ANALYTICS_JOB_PGUSER'] == 'job'
    assert not {'DATABASE_URL','R2_SECRET_ACCESS_KEY','PGHOSTADDR'} & env.keys()
    for url in ['postgresql://postgres:fixture@db.example/postgres',
                'postgresql://job@localhost/churchmap_analytics',
                'postgresql://job@localhost/churchmap_run_abcdef12?hostaddr=203.0.113.1']:
        with pytest.raises(s.GateError):
            d.job_connection(url)
    profile = Path('analytics/dbt/profiles.yml').read_text().split('    job:',1)[1]
    assert 'threads: 1' in profile and 'sslmode: disable' in profile


def test_failure_output_never_echoes_client_or_credential(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv('PROD_READONLY_DATABASE_URL', 'private')
    def fail(url):
        print('PRIVATE PHONE AND NOTES')
        raise RuntimeError('PRIVATE PASSWORD AND URL')
    monkeypatch.setattr(s, 'capture', fail)
    assert s.main(['--report', str(tmp_path/'private.json')]) == 1
    out = capsys.readouterr()
    assert out.err == '' and out.out == '{"step":"cloud_snapshot","status":"failed"}\n'
    assert not (tmp_path/'private.json').exists()
    monkeypatch.setattr(s, 'capture', lambda _: snap())
    assert s.main(['--report', str(tmp_path/'private.json')]) == 0


def test_inspection_does_not_connect_target(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv('PROD_READONLY_DATABASE_URL', 'private')
    monkeypatch.setattr(s, 'capture', lambda _: snap())
    monkeypatch.setattr(s, 'connect', lambda _: pytest.fail('target connection in inspect'))
    report = tmp_path/'report.json'
    assert s.main(['--report', str(report)]) == 0
    assert json.loads(report.read_text())['accepted'] is False
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
    roles = ('churchmap_snapshot_reader',)
    for role in roles:
        assert not admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone(), 'test role collision'
        admin.execute(psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'fixture-only' NOSUPERUSER NOBYPASSRLS").format(psycopg.sql.Identifier(role)))
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
    admin.execute('DROP SCHEMA churchmap_snapshot CASCADE')
    for role in roles:
        admin.execute(psycopg.sql.SQL('DROP ROLE {}').format(psycopg.sql.Identifier(role)))
    admin.close()


@pytest.fixture
def fresh(db):
    admin, urls = db
    admin.execute('TRUNCATE churchmap_snapshot.fixture')
    admin.execute("INSERT INTO churchmap_snapshot.fixture(church_id,name,has_google_address) SELECT n,'synthetic',false FROM generate_series(1,10) n")
    return admin, urls


@pytest.fixture
def disposable(db):
    admin, _ = db
    name = 'churchmap_run_' + uuid.uuid4().hex
    admin.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(name)))
    url = make_conninfo(os.environ['DATABASE_URL'], dbname=name)
    yield url
    admin.execute(psycopg.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(psycopg.sql.Identifier(name)))


def test_real_capture_and_disposable_install(fresh, disposable):
    admin, urls = fresh
    x = s.capture(urls['churchmap_snapshot_reader'])
    assert len(x.rows) == 10 and all(r[-1] is False for r in x.rows)
    d.install(disposable, x)
    with s.connect(disposable) as con:
        assert con.execute('SELECT count(*) FROM raw.churches').fetchone() == (10,)
        assert con.execute('SELECT snapshot_source FROM raw.snapshot_meta').fetchone() == (s.VIEW,)
        con.execute('CREATE VIEW raw.consumer AS SELECT count(*) n FROM raw.churches')
    with pytest.raises(s.GateError, match='target_not_empty'):
        d.install(disposable, x)
    with s.connect(disposable) as con:
        assert con.execute('SELECT n FROM raw.consumer').fetchone() == (10,)


def test_real_copy_failure_rolls_back_all_new_objects(fresh, disposable):
    _, urls = fresh
    x = s.capture(urls['churchmap_snapshot_reader'])
    with pytest.raises(psycopg.errors.UniqueViolation):
        d.install(disposable, replace(x, rows=x.rows+(x.rows[0],)))
    with s.connect(disposable) as con:
        assert con.execute("SELECT count(*) FROM pg_namespace WHERE nspname='raw'").fetchone() == (0,)


def test_real_empty_and_shape_refused(fresh):
    admin, urls = fresh
    admin.execute('TRUNCATE churchmap_snapshot.fixture')
    with pytest.raises(s.GateError, match='empty'):
        s.capture(urls['churchmap_snapshot_reader'])
    admin.execute("CREATE OR REPLACE VIEW churchmap_snapshot.churches AS SELECT *, 'private'::text AS google_address FROM churchmap_snapshot.fixture")
    try:
        with pytest.raises(s.GateError, match='shape'):
            s.capture(urls['churchmap_snapshot_reader'])
    finally:
        admin.execute('DROP VIEW churchmap_snapshot.churches; CREATE VIEW churchmap_snapshot.churches AS SELECT * FROM churchmap_snapshot.fixture; GRANT SELECT ON churchmap_snapshot.churches TO churchmap_snapshot_reader')


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


class FakeS3:
    """ETag/CAS semantics, with independent clients sharing one object store."""
    def __init__(self): self.objects = {}
    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        data = self.objects[Key]
        return {'Body': BytesIO(data), 'ETag': hashlib.sha256(data).hexdigest()}
    def put_object(self, Bucket, Key, Body, **kwargs):
        old = self.objects.get(Key)
        if (kwargs.get('IfNoneMatch') == '*' and old is not None or
                'IfMatch' in kwargs and (old is None or hashlib.sha256(old).hexdigest() != kwargs['IfMatch'])):
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        self.objects[Key] = Body


def accepted(store, x, etag=None):
    return store.accept(x, etag, uuid.uuid4().hex, 'a'*40, '2026-11-04')


def test_r2_first_baseline_and_concurrent_cas():
    client = FakeS3(); store = state.AcceptanceStore(client, 'private')
    assert store.read() == (None, None)
    x = snap()
    accepted(store, x)
    before, etag = store.read()
    with pytest.raises(ClientError): accepted(store, x)  # racing first writers
    newer = replace(x, taken_at=x.taken_at+timedelta(seconds=1))
    accepted(store, newer, etag)
    with pytest.raises(ClientError): accepted(store, x, etag)  # stale ETag
    assert store.read()[0]['taken_at'] == newer.taken_at.isoformat()
    with pytest.raises(s.GateError, match='stale'):
        s.validate_count(x, state.previous_record(store.read()[0]))


@pytest.mark.parametrize('code', ['AccessDenied', 'InternalError', 'NoSuchBucket'])
def test_r2_error_is_not_missing_baseline(code):
    class Broken:
        def get_object(self, **kwargs): raise ClientError({'Error':{'Code':code}}, 'GetObject')
    with pytest.raises(ClientError): state.AcceptanceStore(Broken(),'private').read()


def test_r2_invalid_metadata_and_oversize():
    client=FakeS3();store=state.AcceptanceStore(client,'private')
    accepted(store,snap())
    good=client.objects[state.KEY]
    for change in [{'gate_version':'unknown'}, {'expected_rows':0}, {'dbt_status':'failed'},
                   {'taken_at':'2026-11-04T00:00:00'}]:
        client.objects[state.KEY]=s.encoded({**json.loads(good), **change})
        with pytest.raises(s.GateError):store.read()
    client.objects[state.KEY]=b' '* (state.LIMIT+1)
    with pytest.raises(s.GateError):store.read()


@pytest.mark.parametrize('failure', ['install', 'build', 'conflict', None])
def test_job_only_accepts_after_build(monkeypatch, tmp_path, failure):
    client=FakeS3();store=state.AcceptanceStore(client,'private')
    x=snap();accepted(store,replace(x,taken_at=x.taken_at-timedelta(seconds=1)))
    before=client.objects[state.KEY]
    monkeypatch.setattr(s,'capture',lambda _:x)
    order=[]
    def install(*args):
        order.append('install')
        if failure=='install':raise ValueError('private copy error')
    def build(*args):
        order.append('build')
        if failure=='build':raise ValueError('private dbt error')
        if failure=='conflict':
            _,etag=store.read()
            accepted(store,replace(x,taken_at=x.taken_at+timedelta(seconds=1)),etag)
    monkeypatch.setattr(d,'install',install);monkeypatch.setattr(d,'run_build',build)
    call=lambda:d.run_job('postgresql://job@localhost/churchmap_run_abcdef12','private',store,tmp_path,None,'a'*40)
    if failure:
        with pytest.raises(Exception):call()
        assert not (tmp_path/'accepted.json').exists()
        if failure != 'conflict':assert client.objects[state.KEY]==before
    else:
        assert call()==10 and order==['install','build']
        assert json.loads((tmp_path/'accepted.json').read_text())==store.read()[0]


@pytest.mark.parametrize('count', [0,7])
def test_bad_snapshot_never_installs_or_accepts(monkeypatch,tmp_path,count):
    store=state.AcceptanceStore(FakeS3(),'private');x=snap();accepted(store,x)
    before=store.read()[0]
    monkeypatch.setattr(s,'capture',lambda _:replace(snap(count),taken_at=x.taken_at+timedelta(seconds=1)))
    monkeypatch.setattr(d,'install',lambda *a:pytest.fail('must reject before mutation'))
    with pytest.raises(s.GateError):
        d.run_job('postgresql://job@localhost/churchmap_run_abcdef12','private',store,tmp_path,None,'a'*40)
    assert store.read()[0]==before


@pytest.mark.parametrize('returncode,status', [(0,'pass'),(1,'error'),(0,'skipped')])
def test_dbt_options_and_private_logs(monkeypatch,tmp_path,returncode,status):
    from types import SimpleNamespace
    def run(cmd,**kwargs):
        assert cmd[1:4]==['-m','dbt.cli.main','build']
        assert cmd[cmd.index('--target')+1]=='job'
        assert json.loads(cmd[cmd.index('--vars')+1])=={'as_of_date':'2026-11-04'}
        assert kwargs['timeout']==900
        assert 'R2_SECRET_ACCESS_KEY' not in kwargs['env']
        kwargs['stdout'].write('PRIVATE DBT DETAILS')
        target=Path(cmd[cmd.index('--target-path')+1]);target.mkdir()
        (target/'run_results.json').write_text(json.dumps({'results':[{'status':status}]}))
        return SimpleNamespace(returncode=returncode)
    monkeypatch.setattr(d.subprocess,'run',run)
    call=lambda:d.run_build('postgresql://job@localhost/churchmap_run_abcdef12',tmp_path,'2026-11-04')
    if returncode or status=='skipped':
        with pytest.raises(s.GateError):call()
    else:call()
    assert (tmp_path/'build.log').stat().st_mode & 0o777==0o600


@pytest.mark.parametrize('failure', [False,True])
def test_job_cli_public_output(monkeypatch,tmp_path,capsys,failure):
    class R2:
        bucket='private'
        def _ensure(self):return FakeS3()
    monkeypatch.setattr(d,'R2Client',R2)
    for key in ['ANALYTICS_DATABASE_URL','PROD_READONLY_DATABASE_URL']:monkeypatch.setenv(key,'private')
    monkeypatch.setenv('R2_PRIVATE_CONFIRMED','true')
    def run(*args):
        print('PRIVATE NOTES')
        if failure:raise RuntimeError('PRIVATE PASSWORD')
        return 10
    monkeypatch.setattr(d,'run_job',run)
    directory=tmp_path/'job'
    assert d.main(['--run','--private-dir',str(directory),'--revision','a'*40])==int(failure)
    out=capsys.readouterr()
    assert out.err=='' and 'PRIVATE' not in out.out
    assert json.loads(out.out)['status']==('failed' if failure else 'ok')
    assert directory.stat().st_mode & 0o777==0o700


@pytest.mark.parametrize('limit,value', [('MAX_ROWS',9),('MAX_BYTES',1)])
def test_capture_resource_bounds(fresh,monkeypatch,limit,value):
    _,urls=fresh
    monkeypatch.setattr(s,limit,value)
    with pytest.raises(s.GateError,match='snapshot_limit'):
        s.capture(urls['churchmap_snapshot_reader'])


def test_r2_sdk_supports_both_conditional_writes():
    import boto3
    from botocore.stub import Stubber, ANY
    client=boto3.client('s3',region_name='auto',endpoint_url='https://r2.invalid',
                        aws_access_key_id='fixture',aws_secret_access_key='fixture')
    store=state.AcceptanceStore(client,'private')
    with Stubber(client) as stub:
        for etag in (None,'previous-etag'):
            run=uuid.uuid4().hex
            stub.add_response('put_object',{}, {'Bucket':'private',
                'Key':f'{state.PREFIX}/runs/{run}.json','Body':ANY,
                'ContentType':'application/octet-stream','IfNoneMatch':'*'})
            stub.add_response('put_object',{}, {'Bucket':'private','Key':state.KEY,
                'Body':ANY,'ContentType':'application/json',
                **({'IfMatch':etag} if etag else {'IfNoneMatch':'*'})})
            store.accept(snap(),etag,run,'a'*40,'2026-11-04')
        stub.assert_no_pending_responses()


def test_null_remote_state_cannot_reinitialize():
    client=FakeS3();client.objects[state.KEY]=b'null'
    with pytest.raises(s.GateError):state.AcceptanceStore(client,'private').read()
