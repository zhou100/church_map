"""Bounded sanitized PostgreSQL snapshots. CLI defaults to read-only inspection.

Inspection only: never writes either database. Reports are private; stdout is
restricted to counts/status, including failure paths.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile

import psycopg
from psycopg.conninfo import conninfo_to_dict

FIELDS = ('church_id', 'name', 'address', 'city', 'state', 'zip_code',
          'latitude', 'longitude', 'website', 'phone', 'source', 'external_id',
          'denomination', 'has_google_address')
VIEW = 'churchmap_snapshot.churches'
SCOPE = 'all_congregations_v1'
VERSION = 'snapshot_gate_v1'
MAX_ROWS = 100_000
MAX_BYTES = 64 * 1024 * 1024


class GateError(ValueError):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def connect(url):
    info = conninfo_to_dict(url)
    # Local synthetic tests only; all remote connections enforce TLS regardless
    # of sslmode embedded in the URL. No credentials appear in identity/report.
    local = info.get('host') in {'127.0.0.1', '::1', 'localhost'}
    return psycopg.connect(url, sslmode='disable' if local else 'require',
                           connect_timeout=10, prepare_threshold=None)


def database_identity(con):
    return hashlib.sha256(encoded({'host': con.info.host, 'port': con.info.port,
                                  'database': con.info.dbname})).hexdigest()


def require_role(con, expected):
    row = con.execute('SELECT current_user, rolsuper, rolbypassrls FROM pg_roles '
                      'WHERE rolname=current_user').fetchone()
    if row != (expected, False, False):
        raise GateError('unexpected_role')


@dataclass(frozen=True)
class Snapshot:
    rows: tuple
    identity: str
    taken_at: datetime
    sha256: str
    bytes: int
    scope: str = SCOPE
    database: str = ''


def capture(url):
    rows, size, hasher, seen = [], 0, hashlib.sha256(), set()
    with connect(url) as con:
        con.read_only = True
        con.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        con.execute("SET LOCAL statement_timeout='30s'")
        require_role(con, 'churchmap_snapshot_reader')
        if con.execute('SHOW transaction_read_only').fetchone()[0] != 'on':
            raise GateError('source_not_readonly')
        taken_at = con.execute('SELECT transaction_timestamp()').fetchone()[0]
        database_id = database_identity(con)
        identity = hashlib.sha256(encoded({'database': database_id,
                                          'view': VIEW, 'scope': SCOPE})).hexdigest()
        # Inspect the view's complete shape so an accidental raw column addition
        # is rejected even though the SELECT below never requests it.
        names = con.execute('SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass '
                            'AND attnum>0 AND NOT attisdropped ORDER BY attnum', (VIEW,)).fetchall()
        if tuple(n[0] for n in names) != FIELDS:
            raise GateError('source_shape_changed')
        with con.cursor(name='sanitized_snapshot') as cur:
            cur.execute('SELECT ' + ','.join(FIELDS) + ' FROM ' + VIEW + ' ORDER BY church_id')
            while batch := cur.fetchmany(1000):
                for row in batch:
                    if type(row[0]) is not int or row[0] in seen or type(row[-1]) is not bool:
                        raise GateError('invalid_snapshot_row')
                    data = encoded(row) + b'\n'
                    size += len(data)
                    if len(rows) >= MAX_ROWS or size > MAX_BYTES:
                        raise GateError('snapshot_limit')
                    seen.add(row[0]); rows.append(tuple(row)); hasher.update(data)
    if not rows:
        raise GateError('empty_snapshot')
    return Snapshot(tuple(rows), identity, taken_at, hasher.hexdigest(), size,
                    database=database_id)


def validate_count(snapshot, previous, baseline=None):
    count = len(snapshot.rows)
    if not count:
        raise GateError('empty_snapshot')
    if previous:
        identity, scope, old_count, taken_at = previous
        if identity != snapshot.identity or scope != snapshot.scope:
            raise GateError('source_scope_changed')
        if type(old_count) is not int or old_count <= 0 or taken_at is None:
            raise GateError('invalid_previous_metadata')
        if snapshot.taken_at <= taken_at:
            raise GateError('stale_snapshot')
        if count * 100 < old_count * 80:
            raise GateError('count_drop')
    else:
        if not baseline or baseline.get('identity') != snapshot.identity or baseline.get('scope') != snapshot.scope:
            raise GateError('initial_baseline_required')
        if type(baseline.get('expected_rows')) is not int or baseline['expected_rows'] != count:
            raise GateError('initial_count_mismatch')


def metadata(snapshot):
    return {'identity': snapshot.identity, 'scope': snapshot.scope,
            'database_identity': snapshot.database, 'gate_version': VERSION,
            'expected_rows': len(snapshot.rows), 'sha256': snapshot.sha256,
            'taken_at': snapshot.taken_at.isoformat(), 'bytes': snapshot.bytes}


def write_report(path, result):
    # Publish only complete JSON, never overwrite existing evidence. A failed
    # capture creates no file; failed filesystem operations clean up staging.
    fd, staging = tempfile.mkstemp(prefix='.snapshot-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as report:
            json.dump(result, report)
        os.link(staging, path)
    finally:
        os.unlink(staging)


def load_json(path):
    return json.loads(path.read_text()) if path else None


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise GateError('arguments')


def main(argv=None):
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
            p = SafeParser(description=__doc__)
            p.add_argument('--report', type=Path, required=True)
            args = p.parse_args(argv)
            if args.report.exists() or args.report.is_symlink():
                raise GateError('report_exists')
            snapshot = capture(os.environ['PROD_READONLY_DATABASE_URL'])
            write_report(args.report, {**metadata(snapshot), 'accepted': False})
        print(json.dumps({'step': 'cloud_snapshot', 'status': 'ok',
                          'rows': len(snapshot.rows)}))
        return 0
    except Exception:
        print('{"step":"cloud_snapshot","status":"failed"}')
        return 1
    finally:
        logging.disable(previous_logging)


if __name__ == '__main__':
    sys.exit(main())
