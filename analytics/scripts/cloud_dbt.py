"""Manual analytics job: disposable loopback Postgres + private R2 gate state.

No production writes, role changes, publication or scheduling. The caller owns
creating and destroying the ephemeral service; existing databases are rejected.
"""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo

from psycopg.conninfo import conninfo_to_dict
from analytics.scripts import cloud_snapshot as snapshot
from analytics.scripts.load_snapshot import COLUMNS
from analytics.scripts.snapshot_state import AcceptanceStore, previous_record
from backend.scrapers_v2.r2 import R2Client

PROJECT = Path(__file__).resolve().parents[1] / 'dbt'


def job_connection(url):
    info = conninfo_to_dict(url)
    # Do not allow libpq service/hostaddr/options to redirect or alter this target.
    if (set(info) - {'host', 'port', 'user', 'password', 'dbname', 'sslmode'} or
            info.get('host') not in {'127.0.0.1', 'localhost', '::1'} or
            not info.get('user') or
            not re.fullmatch(r'churchmap_run_[a-f0-9]{8,32}', info.get('dbname', ''))):
        raise snapshot.GateError('disposable_target_required')
    return info


def job_env(url):
    info = job_connection(url)
    # The dbt subprocess gets no production URL, R2 credentials or libpq defaults.
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR',
                                    'SYSTEMROOT') if k in os.environ}
    for key, field in [('HOST','host'), ('PORT','port'), ('USER','user'),
                       ('PASSWORD','password'), ('DATABASE','dbname')]:
        env['ANALYTICS_JOB_PG' + key] = info.get(field, '5432' if field == 'port' else '')
    env['DBT_SEND_ANONYMOUS_USAGE_STATS'] = 'false'
    return env


def install(url, captured):
    info = job_connection(url)
    with snapshot.connect(url) as con:
        con.execute("SET LOCAL statement_timeout='120s'")
        if con.info.dbname != info['dbname']:
            raise snapshot.GateError('wrong_target')
        # A fresh job database has only empty public and system schemas. Never
        # DROP existing data or accept a reused database, even after a failed run.
        occupied = con.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE "
                               "nspname <> 'public' AND nspname <> 'information_schema' "
                               "AND nspname !~ '^pg_') OR EXISTS ("
                               "SELECT 1 FROM pg_class WHERE relnamespace='public'::regnamespace) "
                               "OR EXISTS (SELECT 1 FROM pg_proc WHERE pronamespace='public'::regnamespace)").fetchone()[0]
        if occupied:
            raise snapshot.GateError('target_not_empty')
        con.execute('CREATE SCHEMA raw')
        con.execute('CREATE TABLE raw.churches (' + ','.join(f'{n} {t}' for n,t in COLUMNS) + ')')
        with con.cursor().copy('COPY raw.churches (' + ','.join(snapshot.FIELDS) + ') FROM STDIN') as cp:
            for row in captured.rows:
                cp.write_row(row)
        con.execute('CREATE TABLE raw.snapshot_meta (snapshot_source text, '
                    'snapshot_taken_at timestamptz, loaded_at timestamptz)')
        con.execute('INSERT INTO raw.snapshot_meta VALUES (%s,%s,now())',
                    (snapshot.VIEW, captured.taken_at))


def run_build(url, directory, as_of_date):
    env = job_env(url)
    fd = os.open(directory / 'build.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as log:
        proc = subprocess.run(
            [sys.executable, '-m', 'dbt.cli.main', 'build',
             '--project-dir', str(PROJECT), '--profiles-dir', str(PROJECT),
             '--target', 'job', '--full-refresh',
             '--log-path', str(directory.resolve() / 'logs'),
             '--target-path', str(directory.resolve() / 'target'),
             '--vars', json.dumps({'as_of_date': as_of_date})],
            env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900,
        )
    if proc.returncode:
        raise snapshot.GateError('dbt_failed')
    # Return code alone is not evidence that all selected models/tests ran.
    result = json.loads((directory / 'target/run_results.json').read_text())
    if not result.get('results') or any(r['status'] not in {'success', 'pass'} for r in result['results']):
        raise snapshot.GateError('dbt_incomplete')


def run_job(url, source_url, store, directory, baseline, revision):
    job_connection(url)  # reject remote targets before any source/network work
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise snapshot.GateError('invalid_revision')
    previous, etag = store.read()
    captured = snapshot.capture(source_url)
    snapshot.validate_count(captured, previous_record(previous), baseline)
    install(url, captured)
    today = datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
    run_build(url, directory, today)
    # CAS prevents parallel jobs that read the same baseline overwriting each
    # other. Only this success may proceed downstream; this code never publishes.
    receipt = store.accept(captured, etag, uuid.uuid4().hex, revision, today)
    snapshot.write_report(directory / 'accepted.json', receipt)
    return len(captured.rows)


def main(argv=None):
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
            p = snapshot.SafeParser(description=__doc__)
            p.add_argument('--run', action='store_true', required=True)
            p.add_argument('--baseline', type=Path)
            p.add_argument('--private-dir', type=Path, required=True)
            p.add_argument('--revision', required=True)
            args = p.parse_args(argv)
            if os.environ.get('R2_PRIVATE_CONFIRMED') != 'true':
                raise snapshot.GateError('private_store_required')
            args.private_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
            r2 = R2Client()
            store = AcceptanceStore(r2._ensure(), r2.bucket)
            count = run_job(os.environ['ANALYTICS_DATABASE_URL'],
                            os.environ['PROD_READONLY_DATABASE_URL'], store,
                            args.private_dir, snapshot.load_json(args.baseline), args.revision)
        print(json.dumps({'step': 'cloud_dbt', 'status': 'ok', 'rows': count}))
        return 0
    except Exception:
        print('{"step":"cloud_dbt","status":"failed"}')
        return 1
    finally:
        logging.disable(previous_logging)


if __name__ == '__main__':
    sys.exit(main())
