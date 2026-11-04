"""Manual private Muse shadow run. All state mutations occur in a new temp copy."""
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import csv
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback

from scripts.muse_state_store import (Store, ROOTS, MAX_FILE, MAX_FILES, MAX_TOTAL,
                                     digest, restore, save, manifest_key)
from scripts.muse_drive_r2_check import DriveReader, FOLDER

PREFIX = 'analytics_private/v1/shadow'
STATES = {'queued', 'started', 'delivered', 'needs_fix', 'pending_build', 'build_failed', 'ingested'}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as out:
        os.chmod(path, 0o600)
        json.dump(value, out, sort_keys=True, indent=2)


def rows(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as source:
        return list(csv.DictReader(source))


def copy_code(source, destination):
    # No ignored local state, credentials, database or virtualenv enters the copy.
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others',
                                     '--exclude-standard'], cwd=source).decode().split('\0')
    destination.mkdir()
    for name in names:
        if name != 'dedup_report.csv' and not name.startswith(('scripts/', 'backend/', 'analytics/', 'muse_handoff/')):
            continue
        if any(name.startswith(scope + '/') for scope in ROOTS):
            continue
        src, dst = source / name, destination / name
        if src.is_symlink() or not src.is_file():
            raise ValueError('unsafe code file')
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def mirror_drive(reader, folder, target):
    """Bound every file/tree; retain Drive mtimes (pull's received_at input).

    Missing/oversized output files are left missing, so existing pull waits rather
    than ingesting them. Hash mismatches likewise reach pull's existing gate.
    Ambiguous paths and changing DONE fail the run before pull.
    """
    target.mkdir()
    returns = reader.named(folder, 'returns', FOLDER)
    seen_ids, inventory, omitted = set(), {}, 0
    total = 0

    def walk(folder_id, directory, depth=0):
        nonlocal total, omitted
        if folder_id in seen_ids or depth > 12:
            raise ValueError('Drive cycle/depth')
        seen_ids.add(folder_id)
        directory.mkdir(parents=True)
        names = set()
        for entry in reader.children(folder_id):
            name = entry['name']
            if (not isinstance(name, str) or name in {'.', '..', ''} or
                    '/' in name or '\\' in name or name in names):
                raise ValueError('unsafe/duplicate Drive name')
            names.add(name)
            if len(inventory) + len(seen_ids) + omitted >= MAX_FILES:
                raise ValueError('Drive tree limit')
            path = directory / name
            if entry['mimeType'] == FOLDER:
                walk(entry['id'], path, depth + 1)
                continue
            if entry['mimeType'].startswith('application/vnd.google-apps.'):
                raise ValueError('unsupported Drive file')
            if int(entry['size']) > MAX_FILE:
                omitted += 1
                continue
            data = reader.download(entry['id'])  # independently bounded streaming reader
            if len(data) > MAX_FILE:
                raise ValueError('Drive file limit')
            total += len(data)
            if total > MAX_TOTAL:
                raise ValueError('Drive total limit')
            stamp = datetime.fromisoformat(entry['modifiedTime'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('Drive time missing timezone')
            path.write_bytes(data)
            os.utime(path, (stamp.timestamp(), stamp.timestamp()))
            inventory[path.relative_to(target).as_posix()] = {
                'sha256': digest(data), 'modified_at': entry['modifiedTime'], 'bytes': len(data)}
        # DONE must be stable across this package download, including its mtime.
        if 'DONE.md' in names:
            after = reader.named(folder_id, 'DONE.md', next(
                e['mimeType'] for e in reader.children(folder_id) if e['name'] == 'DONE.md'))
            path = directory / 'DONE.md'
            if not path.exists() or reader.download(after['id']) != path.read_bytes():
                raise ValueError('Drive DONE changed')
            if after['modifiedTime'] != inventory[path.relative_to(target).as_posix()]['modified_at']:
                raise ValueError('Drive DONE time changed')

    packages = reader.children(returns['id'])
    names = [p['name'] for p in packages if re.fullmatch(r'WP-\d{4}', p['name'])]
    if len(names) != len(set(names)):
        raise ValueError('duplicate package')
    (target / 'returns').mkdir()
    for package in packages:
        if not re.fullmatch(r'WP-\d{4}', package['name']):
            continue
        if package['mimeType'] != FOLDER:
            raise ValueError('invalid package')
        walk(package['id'], target / 'returns' / package['name'])
    return {'files': inventory, 'oversized_files': omitted}


def file_report(root):
    status = {r['wp_id']: r for r in rows(root / 'muse_handoff/outbox/status.csv')}
    checks = {}
    for path in sorted((root / 'muse_handoff/returns/recheck').glob('*.csv')):
        checks[path.name] = dict(Counter(r['verdict'] for r in rows(path)))
    return {'packages': status,
            'received': rows(root / 'muse_handoff/returns/received.csv'),
            'seed_sha256': {p.name: digest(p.read_bytes()) for p in sorted(
                (root / 'analytics/dbt/seeds').glob('*.csv'))},
            'recheck_verdicts': checks}


def database_counts(root, url, disposable=True):
    import psycopg
    from psycopg.rows import dict_row
    if disposable:
        from analytics.scripts.cloud_dbt import job_connection
        job_connection(url)
    # Reuse the geocoder's actual eligibility and exact-address ledger keys.
    sys.path.insert(0, str(root / 'analytics/scripts'))
    import geocode_incremental as geo
    ledger = root / 'analytics/exports/geocode_ledger.csv'
    if ledger.exists():
        known = {geo.key(r) for r in rows(ledger)}
    else:
        # Bind legacy output exactly as the existing geocoder does, without writes.
        geo.EXPORTS = root / 'analytics/exports'
        geo.OUTPUT = geo.EXPORTS / 'geocode_output.csv'
        geo.RECEIPT = geo.EXPORTS / 'geocode_reconciliation.json'
        known = {geo.key(r) for r in geo.seed_ledger()} if geo.OUTPUT.exists() else set()
    with psycopg.connect(url, prepare_threshold=None, row_factory=dict_row) as con:
        con.execute('SET TRANSACTION READ ONLY')
        con.execute("SET LOCAL statement_timeout='60s'")
        counts = {}
        for name in ('mart_publish_churches', 'mart_publish_new', 'mart_new_congregations'):
            counts[name] = con.execute('SELECT count(*) AS n FROM analytics.' + name).fetchone()['n']
        counts['directory_rows'] = con.execute('SELECT count(*) AS n FROM raw.churches').fetchone()['n']
        eligible = con.execute(geo.INPUT_SQL).fetchall()
        counts['pending_geocode_addresses'] = sum(geo.key(r) not in known for r in eligible)
    return counts


def child(root, private, step, args, env):
    with (private / (step + '.log')).open('xb') as log:
        proc = subprocess.run([sys.executable, *args], cwd=root, env=env,
                              stdout=log, stderr=subprocess.STDOUT, timeout=3600)
    if proc.returncode:
        raise RuntimeError('child failed')


def archive(store, directory, run_id):
    manifest_key(run_id)
    entries, total = [], 0
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('archive symlink')
        if not path.is_file():
            continue
        data = path.read_bytes()
        total += len(data)
        if len(data) > MAX_FILE or total > MAX_TOTAL or len(entries) >= MAX_FILES:
            raise ValueError('archive limit')
        name = path.relative_to(directory).as_posix()
        store.put_once(f'{PREFIX}/{run_id}/{name}', data)
        entries.append({'path': name, 'sha256': digest(data), 'bytes': len(data)})
    store.put_once(f'{PREFIX}/{run_id}/manifest.json', json.dumps(entries, sort_keys=True).encode())
    return len(entries)


def pipeline(source, work, store, reader, folder, run_id, initial_id, initial_hash,
             revision, env, run_child=child, count_db=database_counts):
    manifest_key(run_id)
    manifest_key(run_id + '-state')
    if run_id == initial_id or run_id + '-state' == initial_id:
        raise ValueError('shadow must have distinct identity')
    private = work / 'private'
    private.mkdir(mode=0o700)
    root, bundle = work / 'checkout', work / 'archive'
    bundle.mkdir(mode=0o700)
    step, status, counts = 'restore', 'failed', {}
    try:
        restore(store, work / 'initial', initial_id, initial_hash)
        copy_code(source, root)
        for scope in ROOTS:
            src = work / 'initial' / scope
            if not src.is_dir():
                raise ValueError('incomplete state snapshot')
            shutil.copytree(src, root / scope)
        write_json(bundle / 'before.json', file_report(root))
        step = 'drive'
        drive = work / 'drive'
        inputs = mirror_drive(reader, folder, drive)
        write_json(bundle / 'inputs.json', {'snapshot_run': initial_id,
                   'manifest_sha256': initial_hash, 'revision': revision, 'drive': inputs})
        safe_env = {k: env[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR') if k in env}
        safe_env.update(CHURCHMAP_DRIVE=str(drive), CHURCHMAP_ANALYTICS_PYTHON=sys.executable)
        step = 'pull'
        run_child(root, private, step, ['muse_handoff/drive_sync.py', 'pull', '--no-build', '--no-geocode'], safe_env)
        step = 'seeds'
        run_child(root, private, step, ['analytics/scripts/build_seeds.py'], safe_env)
        step = 'dbt'
        dbt_env = {**safe_env, **{k: v for k, v in env.items() if k.startswith('R2_') or k in
                     ('ANALYTICS_DATABASE_URL', 'PROD_READONLY_DATABASE_URL')}}
        args = ['-m', 'analytics.scripts.cloud_dbt', '--run', '--revision', revision,
                '--private-dir', str(private / 'dbt')]
        if env.get('MUSE_BASELINE_IDENTITY'):
            write_json(private / 'baseline.json', {'identity': env['MUSE_BASELINE_IDENTITY'],
                'scope': env['MUSE_BASELINE_SCOPE'], 'expected_rows': int(env['MUSE_BASELINE_ROWS'])})
            args += ['--baseline', str(private / 'baseline.json')]
        run_child(root, private, step, args, dbt_env)
        step = 'counts'
        counts = count_db(root, env['ANALYTICS_DATABASE_URL'])
        status = 'ok'
    except Exception:
        write_json(private / 'failure.json', {'step': step, 'traceback': traceback.format_exc()})
    finally:
        # Archive failures too; no authoritative pointer is advanced by this code.
        if root.exists() and all((root / p).exists() for p in ROOTS):
            write_json(bundle / 'after.json', {**file_report(root), 'counts': counts, 'status': status})
            receipt = save(store, root, run_id + '-state', revision)
            write_json(bundle / 'state-receipt.json', {**receipt, 'run_id': run_id + '-state'})
        if (work / 'drive').exists():
            shutil.copytree(work / 'drive', bundle / 'drive')
        shutil.copytree(private, bundle / 'private')
        if root.exists():
            packages = file_report(root)['packages']
        else:
            packages = {}
        digest_rows = [{k: r.get(k, '') for k in ('wp_id', 'state', 'published_at',
                        'started_at', 'delivered_at', 'ingested_at')}
                       for r in packages.values() if re.fullmatch(r'WP-\d{4}', r.get('wp_id', ''))
                       and r.get('state') in STATES]
        # No source log tails, URLs, notes or fabricated crawler/publication counts.
        write_json(bundle / 'status_digest.json', {'step': step, 'status': status,
                   'packages': digest_rows, 'counts': counts,
                   'fetch': 'not_observed', 'extract': 'not_observed', 'tag': 'not_observed',
                   'publish': 'not_run', 'window_24h': 'not_measured'})
        archived = archive(store, bundle, run_id)
    return {'step': 'shadow', 'status': status, 'files': archived, **counts,
            **({'error_code': 'shadow_failed'} if status != 'ok' else {})}


def main():
    import tempfile
    from backend.scrapers_v2.r2 import R2Client
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    old_umask = os.umask(0o077)
    result = {'step': 'shadow', 'status': 'failed', 'error_code': 'shadow_failed'}
    try:
        with tempfile.TemporaryDirectory(prefix='muse-shadow-', dir=os.environ.get('RUNNER_TEMP')) as tmp:
            # Catch provider/setup output as well as subprocesses. Never relay error strings.
            with open(Path(tmp) / 'setup.log', 'w') as log, redirect_stdout(log), redirect_stderr(log):
                if os.environ.get('R2_PRIVATE_CONFIRMED') != 'true':
                    raise ValueError('private store required')
                from google.oauth2 import service_account
                from google.auth.transport.requests import AuthorizedSession
                credentials = service_account.Credentials.from_service_account_info(
                    json.loads(os.environ['GDRIVE_SA_JSON']),
                    scopes=['https://www.googleapis.com/auth/drive.readonly'])
                r2 = R2Client()
                with AuthorizedSession(credentials) as session:
                    result = pipeline(Path(__file__).resolve().parents[1], Path(tmp),
                        Store(r2._ensure(), r2.bucket), DriveReader(session), os.environ['GDRIVE_FOLDER_ID'],
                        'shadow-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT'],
                        os.environ['MUSE_STATE_RUN_ID'], os.environ['MUSE_STATE_MANIFEST_SHA256'],
                        os.environ['GITHUB_SHA'], dict(os.environ))
    except Exception:
        pass
    finally:
        os.umask(old_umask)
        logging.disable(previous)
    line = json.dumps(result)
    print(line)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as out:
            out.write(line + '\n')
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
