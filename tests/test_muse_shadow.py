"""Offline shadow orchestration: real pull/validator/recheck/seeds, fake providers."""
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import shutil
import sys

import pytest
from botocore.exceptions import ClientError
from scripts import muse_shadow as s
from scripts import muse_shadow_compare as compare
from scripts.muse_state_store import Store, save, manifest_key

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = 'Private Congregation https://private.example/ verbatim-private-excerpt 650-555-0199'


class S3:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
        if (IfNoneMatch == '*' and Key in self.objects or
                IfMatch and s.digest(self.objects.get(Key, b'')) != IfMatch):
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'put')
        self.objects[Key] = Body

    def get_object(self, *, Key, **kw):
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'get')
        return {'Body': io.BytesIO(self.objects[Key]), 'ETag': s.digest(self.objects[Key])}


class Reader:
    def __init__(self, packages):
        self.tree = {'root': [dict(id='returns', name='returns', mimeType=s.FOLDER)], 'returns': []}
        self.data = {}
        for wp, files in packages.items():
            self.tree['returns'].append(dict(id=wp, name=wp, mimeType=s.FOLDER))
            self.tree[wp] = []
            for name, data in files.items():
                id_ = wp + name
                self.tree[wp].append(dict(id=id_, name=name, mimeType='text/markdown' if name.endswith('.md') else 'text/csv',
                                        size=str(len(data)), modifiedTime='2026-11-04T12:00:00Z'))
                self.data[id_] = data

    def children(self, folder):
        return self.tree[folder]

    def named(self, folder, name, mime):
        matches = [x for x in self.children(folder) if x['name'] == name]
        assert len(matches) == 1 and matches[0]['mimeType'] == mime
        return matches[0]

    def download(self, id_):
        return self.data[id_]


def csv_bytes(cols, rows):
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    return out.getvalue().encode()


@pytest.fixture
def setup(tmp_path):
    initial = tmp_path / 'owner'
    for scope in s.ROOTS:
        (initial / scope).mkdir(parents=True)
    (initial / 'analytics/exports/geocode_ledger.csv').write_text('geo_id,street,city,state,zip\n')
    (initial / 'muse_handoff/returns/received.csv').write_text('file,wp_id,received_at,done_sha256\n')
    (initial / 'muse_handoff/outbox/status.csv').write_bytes(csv_bytes(
        ['wp_id', 'title', 'state'], [dict(wp_id=f'WP-000{i}', title=PRIVATE, state='queued') for i in (1, 2, 3)]))
    (initial / 'muse_handoff/returns/audit_key.csv').write_text('church_id,field,muse_value\n1,status,active\n')
    (initial / 'muse_handoff/returns/audit_worksheet.csv').write_text('church_id,field,your_answer,stratum\n1,status,active,synthetic\n')
    cols = (ROOT / 'muse_handoff/new_candidates_TEMPLATE_v3.csv').read_text().splitlines()[0].split(',')
    good = dict.fromkeys(cols, '')
    good.update(candidate_ref='WP0001-001', task='WP0001', candidate_name='Private Congregation', city='Fixture',
                state='CA', status='unresolved', found_via='web_search', match_confidence='low', notes=PRIVATE)
    # URL is loopback: real rechecker must reject it without making network calls.
    good.update(kids_program_verbatim='verbatim-private-excerpt', kids_source_url='http://127.0.0.1/private',
                kids_source_type='own_site', kids_excerpt='verbatim-private-excerpt', checked_at='2026-11-03T12:00:00Z')
    bad = {**good, 'candidate_ref': 'WP0002-001', 'task': 'WP0002', 'status': 'INVALID'}
    packages = {}
    for i, row in [(1, good), (2, bad), (3, good)]:
        data = csv_bytes(cols, [row])
        sha = s.digest(data) if i != 3 else '0' * 64
        packages[f'WP-000{i}'] = {'new_candidates.csv': data,
                                 'DONE.md': f'new_candidates.csv sha256={sha}\n'.encode()}
    client = S3()
    store = Store(client, 'private')
    receipt = save(store, initial, 'initial', 'a' * 40)
    return initial, client, store, receipt, Reader(packages)


def run_pipeline(tmp_path, setup, fail=False, real_dbt=False, url=None):
    initial, client, store, receipt, reader = setup
    work = tmp_path / 'work'
    work.mkdir()
    source = tmp_path / 'source'
    s.copy_code(ROOT, source)
    # A bounded synthetic corpus, with no historical manifest obligations.
    for path in [*(source / 'muse_handoff').glob('*manifest*.csv'), source / 'muse_handoff/peninsula_seed_v1.csv']:
        path.unlink()
    # copy_code uses git inventory; make a tiny local fixture repository.
    import subprocess
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    env = dict(os.environ, ANALYTICS_DATABASE_URL=url or 'postgresql://fixture@127.0.0.1/churchmap_run_abcdef12')
    old = dict(client.objects)
    owner_bytes = {p: p.read_bytes() for p in initial.rglob('*') if p.is_file()}

    def child(root, private, step, args, child_env):
        assert 'GDRIVE_SA_JSON' not in child_env and 'DATABASE_URL' not in child_env
        if step != 'dbt':
            return s.child(root, private, step, args, child_env)
        if fail:
            print(PRIVATE)
            raise RuntimeError(PRIVATE)
        if real_dbt:
            return real_dbt(root, private, step, args, child_env)
        (private / 'dbt').mkdir()
        s.write_json(private / 'dbt/accepted.json', {'as_of_date': '2026-11-04'})
        (private / 'dbt/build.log').write_text(PRIVATE)

    # Exercise the same public boundary used by Actions, including provider setup.
    result = s.pipeline(source, work, store, reader, 'root', 'shadow-test', 'initial',
                        receipt['manifest_sha256'], 'a' * 40, env, run_child=child,
                        count_db=s.database_counts if real_dbt else lambda *_: {'directory_rows': 1, 'mart_publish_churches': 0,
                                           'mart_publish_new': 0, 'pending_geocode_addresses': 0},
                        export_db=s.published_candidates if real_dbt else lambda *_: [])
    assert all(client.objects[k] == v for k, v in old.items())
    assert all(p.read_bytes() == value for p, value in owner_bytes.items())
    return result, work


@pytest.mark.parametrize('fail', [False, True])
def test_end_to_end_private_boundary(tmp_path, setup, monkeypatch, capsys, fail):
    # Invoke main, with only remote authorization/session construction replaced.
    import google.oauth2.service_account
    import google.auth.transport.requests
    from backend.scrapers_v2.r2 import R2Client
    monkeypatch.setattr(google.oauth2.service_account.Credentials, 'from_service_account_info', lambda *a, **k: None)
    class Session:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
    monkeypatch.setattr(google.auth.transport.requests, 'AuthorizedSession', Session)
    monkeypatch.setattr(R2Client, '_ensure', lambda *_: None)
    original = s.pipeline
    results = []
    def operation(*a, **kw):
        monkeypatch.setattr(s, 'pipeline', original)
        result, work = run_pipeline(tmp_path, setup, fail)
        results.append((result, work))
        return result
    monkeypatch.setattr(s, 'pipeline', operation)
    for key in ('GDRIVE_FOLDER_ID', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'MUSE_STATE_RUN_ID',
                'MUSE_STATE_MANIFEST_SHA256', 'GITHUB_SHA', 'R2_ACCOUNT_ID', 'R2_BUCKET',
                'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'ANALYTICS_DATABASE_URL',
                'PROD_READONLY_DATABASE_URL'):
        monkeypatch.setenv(key, 'fixture')
    monkeypatch.setenv('GDRIVE_SA_JSON', '{}')
    monkeypatch.setenv('R2_PRIVATE_CONFIRMED', 'true')
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(tmp_path / 'summary'))
    assert s.main() == int(fail)
    output = capsys.readouterr()
    assert output.err == ''
    public = json.loads(output.out)
    assert set(public) <= {'step', 'status', 'files', 'error_code', 'directory_rows',
                          'mart_publish_churches', 'mart_publish_new', 'pending_geocode_addresses'}
    assert (tmp_path / 'summary').read_text() == output.out
    for secret in PRIVATE.split():
        assert secret not in output.out
    result, work = results[0]
    after = json.loads((work / 'archive/after.json').read_text())
    assert after['packages']['WP-0001']['state'] == 'pending_build'
    assert after['packages']['WP-0002']['state'] == 'needs_fix'
    assert after['packages']['WP-0003']['state'] == 'queued'
    assert after['received'][0]['received_at'] == '2026-11-04T12:00:00Z'
    assert after['recheck_verdicts']['new_candidates_WP0001.csv']['unsafe_url'] == 1
    assert (work / 'archive/drive/feedback/WP-0002.md').exists()
    assert (work / 'archive/drive/reference/BRIEF_v3.md').exists()
    assert (work / 'archive/private/pull.log').exists()
    assert (work / 'archive/private/seeds.log').exists()
    if fail:
        assert PRIVATE in (work / 'archive/private/failure.json').read_text()
    target = tmp_path / 'download'
    compare.download(setup[2], 'shadow-test', target)
    assert (target / 'after.json').read_bytes() == (work / 'archive/after.json').read_bytes()
    assert json.loads((target / 'state-receipt.json').read_text())['run_id'] == 'shadow-test-state'


@pytest.mark.parametrize('problem', ['oversize', 'duplicate', 'traversal', 'changed'])
def test_drive_bounds_and_identity(tmp_path, setup, problem):
    reader = setup[-1]
    entry = reader.tree['WP-0001'][0]
    if problem == 'oversize':
        entry['size'] = str(s.MAX_FILE + 1)
        result = s.mirror_drive(reader, 'root', tmp_path / 'mirror')
        assert result['oversized_files'] == 1
        assert not (tmp_path / 'mirror/returns/WP-0001/new_candidates.csv').exists()
        return
    if problem == 'duplicate':
        reader.tree['WP-0001'].append(entry.copy())
    if problem == 'traversal':
        entry['name'] = '../escape'
    if problem == 'changed':
        original = reader.download
        seen = set()
        def changed(id_):
            data = original(id_)
            if id_.endswith('DONE.md') and id_ in seen:
                return data + b'changed'
            seen.add(id_)
            return data
        reader.download = changed
    with pytest.raises((ValueError, AssertionError)):
        s.mirror_drive(reader, 'root', tmp_path / 'mirror')


def test_comparison_does_not_excuse_mart_or_seed_differences():
    base = dict(packages={}, received=[], seed_sha256={}, recheck_verdicts={})
    shadow = {**base, 'status': 'ok', 'counts': {'directory_rows': 134377, 'mart_publish_new': 8}}
    local = {**base, 'counts': {'directory_rows': 133939, 'mart_publish_new': 9}, 'seed_sha256': {'x': 'changed'}}
    report = compare.compare(base, shadow, local)
    assert 'directory_rows' in report['expected']
    assert 'counts.mart_publish_new' in report['unexplained']
    assert 'seed_sha256' in report['unexplained']


def test_real_disposable_dbt_pipeline(tmp_path, setup, monkeypatch):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from analytics.scripts import cloud_dbt, cloud_snapshot, snapshot_state
    import uuid
    url = os.environ.get('DATABASE_URL')
    if not url:
        pytest.skip('isolated Postgres DATABASE_URL required')
    info = conninfo_to_dict(url)
    assert info['host'] in {'127.0.0.1', 'localhost'} and info['dbname'].endswith('_test')
    name = 'churchmap_run_' + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        disposable = make_conninfo(url, dbname=name)
        # Row 2 is a congregation published earlier whose candidate is gone: the
        # build must pass and the private archive must name it (review of #80).
        captured = cloud_snapshot.Snapshot(
            ((1, 'Synthetic directory congregation', *([None] * 11), False),
             (2, PRIVATE, *([None] * 8), 'muse', 'C-GONE', None, False)),
            'synthetic-source', datetime.now(timezone.utc), 'a' * 64, 100)
        monkeypatch.setattr(cloud_snapshot, 'capture', lambda _: captured)
        def dbt(root, private, step, args, env):
            monkeypatch.setattr(cloud_dbt, 'PROJECT', root / 'analytics/dbt')
            folder = private / 'dbt'
            folder.mkdir()
            cloud_dbt.run_job(disposable, 'offline-source', snapshot_state.AcceptanceStore(setup[1], 'private'),
                folder, {'identity': captured.identity, 'scope': captured.scope, 'expected_rows': 2}, 'a' * 40)
        try:
            result, work = run_pipeline(tmp_path, setup, real_dbt=dbt, url=disposable)
            assert result['status'] == 'ok', (work / 'private/failure.json').read_text() if (work / 'private/failure.json').exists() else result
            assert result['directory_rows'] == 2
            assert result['mart_publish_new'] == 0
            assert (result['published_candidates'], result['published_not_current']) == (1, 1)
            exported = json.loads((work / 'archive/published_candidates.json').read_text())
            assert [(r['church_id'], r['candidate_id'], r['publication_status']) for r in exported] == [
                (2, 'C-GONE', 'unknown_candidate')]
            assert PRIVATE not in json.dumps(result)
            assert result['pending_geocode_addresses'] == 0
            run_results = json.loads((work / 'archive/private/dbt/target/run_results.json').read_text())
            assert run_results['results'] and all(r['status'] in {'success', 'pass'} for r in run_results['results'])
            assert any(k.endswith('accepted.json') for k in setup[1].objects)
        finally:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.mark.parametrize('failure,code', [
    ('missing', 'missing_config'), ('privacy', 'private_store_required'),
    ('auth', 'drive_auth_failed'), ('r2', 'r2_unavailable'),
])
def test_setup_failure_codes_never_leak(tmp_path, monkeypatch, capsys, failure, code):
    import google.oauth2.service_account
    from backend.scrapers_v2.r2 import R2Client
    for key in ('GDRIVE_SA_JSON', 'GDRIVE_FOLDER_ID', 'R2_ACCOUNT_ID', 'R2_BUCKET',
                'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'GITHUB_RUN_ID',
                'GITHUB_RUN_ATTEMPT', 'MUSE_STATE_RUN_ID', 'MUSE_STATE_MANIFEST_SHA256',
                'GITHUB_SHA', 'ANALYTICS_DATABASE_URL', 'PROD_READONLY_DATABASE_URL'):
        monkeypatch.setenv(key, PRIVATE)
    monkeypatch.setenv('GDRIVE_SA_JSON', '{}')
    monkeypatch.setenv('R2_PRIVATE_CONFIRMED', 'true')
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(tmp_path / 'summary'))
    def fail(*a, **kw):
        print(PRIVATE)
        raise RuntimeError(PRIVATE)
    if failure == 'missing':
        monkeypatch.delenv('GITHUB_SHA')
    elif failure == 'privacy':
        monkeypatch.setenv('R2_PRIVATE_CONFIRMED', 'false')
    elif failure == 'auth':
        monkeypatch.setattr(google.oauth2.service_account.Credentials, 'from_service_account_info', fail)
    else:
        monkeypatch.setattr(google.oauth2.service_account.Credentials, 'from_service_account_info', lambda *a, **kw: None)
        monkeypatch.setattr(R2Client, '_ensure', fail)
    assert s.main() == 1
    output = capsys.readouterr()
    assert output.err == ''
    assert json.loads(output.out) == {'step': 'shadow', 'status': 'failed', 'error_code': code}
    assert (tmp_path / 'summary').read_text() == output.out
