"""Manual, gated cloud dbt build. Private logs only; no scheduling/publishing."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

from psycopg.conninfo import conninfo_to_dict
from analytics.scripts.cloud_snapshot import (
    GateError, LOCK_ID, SafeParser, capacity_gate, connect, load_json, require_role,
)

PROJECT = Path(__file__).resolve().parents[1] / 'dbt'


def cloud_env(url):
    parsed = conninfo_to_dict(url)
    if not all(parsed.get(k) for k in ('host', 'user', 'password', 'dbname')):
        raise GateError('incomplete_cloud_connection')
    if parsed.get('port', '5432') != '5432':
        raise GateError('session_connection_required')
    role = parsed['user'].split('.', 1)[0]
    if role != 'churchmap_analytics':
        raise GateError('cloud_role')
    env = os.environ.copy()
    for key, field in [('HOST','host'), ('PORT','port'), ('USER','user'),
                       ('PASSWORD','password'), ('DATABASE','dbname')]:
        env['ANALYTICS_CLOUD_PG' + key] = parsed.get(field, '5432' if field == 'port' else '')
    env['DBT_PROFILES_DIR'] = str(PROJECT)
    env['DBT_SEND_ANONYMOUS_USAGE_STATS'] = 'false'
    # Keep generated compiled SQL, logs and caches out of the public checkout.
    return env


def main(argv=None):
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
            p = SafeParser(description=__doc__)
            p.add_argument('--capacity-evidence', type=Path, required=True)
            p.add_argument('--private-dir', type=Path, required=True)
            args = p.parse_args(argv)
            url = os.environ['ANALYTICS_DATABASE_URL']
            env = cloud_env(url)
            args.private_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
            env['DBT_LOG_PATH'] = str(args.private_dir.resolve() / 'logs')
            env['DBT_TARGET_PATH'] = str(args.private_dir.resolve() / 'target')
            today = datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
            # Hold the same transaction advisory lock used by snapshot installs
            # through dbt completion. Do not use session locks through a pooler.
            with connect(url) as con:
                require_role(con, 'churchmap_analytics')
                con.execute("SET LOCAL statement_timeout='15s'")
                if not con.execute('SELECT pg_try_advisory_xact_lock(%s)', (LOCK_ID,)).fetchone()[0]:
                    raise GateError('analytics_busy')
                capacity_gate(con, load_json(args.capacity_evidence))
                meta = con.execute('SELECT snapshot_identity,snapshot_row_count,'
                                   'snapshot_gate_version FROM raw.snapshot_meta').fetchall()
                if len(meta) != 1 or not meta[0][0] or not meta[0][1] or meta[0][2] != 'snapshot_gate_v1':
                    raise GateError('accepted_snapshot_required')
                fd = os.open(args.private_dir / 'build.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as log:
                    proc = subprocess.run(
                        [sys.executable, '-m', 'dbt.cli.main', 'build',
                         '--project-dir', str(PROJECT), '--profiles-dir', str(PROJECT),
                         '--target', 'cloud', '--full-refresh',
                         '--vars', json.dumps({'as_of_date': today})],
                        env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900,
                    )
                if proc.returncode:
                    raise GateError('dbt_failed')
        print('{"step":"cloud_dbt","status":"ok"}')
        return 0
    except Exception:
        print('{"step":"cloud_dbt","status":"failed"}')
        return 1
    finally:
        logging.disable(previous_logging)


if __name__ == '__main__':
    sys.exit(main())
