"""Bounded sanitized PostgreSQL snapshots. CLI defaults to read-only inspection.

Only explicit --apply writes analytics. Neither mode writes the source. Reports
are private; stdout is restricted to counts/status, including failure paths.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys

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
LOCK_ID = 731704601
MIGRATION = Path(__file__).resolve().parents[1] / 'migrations/0001_snapshot_gate.sql'


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


def capacity_gate(con, evidence, payload_bytes=0):
    used = con.execute('SELECT pg_database_size(current_database())').fetchone()[0]
    rebuilt = con.execute("SELECT coalesce(sum(pg_total_relation_size(c.oid)),0) "
                          "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                          "WHERE n.nspname IN ('raw','analytics','analytics_seeds') "
                          "AND c.relkind IN ('r','m')").fetchone()[0]
    growth = max(128_000_000, 2 * int(rebuilt), 4 * payload_bytes)
    if used >= 300_000_000 or used + growth >= 400_000_000:
        raise GateError('capacity_limit')
    if not evidence or evidence.get('database_identity') != database_identity(con):
        raise GateError('disk_evidence_required')
    observed = datetime.fromisoformat(evidence['observed_at'])
    age = datetime.now(timezone.utc) - observed
    if age < timedelta(0) or age > timedelta(hours=1):
        raise GateError('disk_evidence_stale')
    free = evidence.get('disk_free_bytes')
    if type(free) is not int or free < growth:
        raise GateError('disk_headroom')
    # Disk/WAL free space is operator evidence, not inferred from DB size.


def install(con, snapshot, baseline, evidence):
    # Caller owns this transaction. Any failure rolls back DDL, data and metadata.
    require_role(con, 'churchmap_analytics')
    con.execute("SET LOCAL lock_timeout='3s'")
    con.execute("SET LOCAL statement_timeout='120s'")
    if not con.execute('SELECT pg_try_advisory_xact_lock(%s)', (LOCK_ID,)).fetchone()[0]:
        raise GateError('analytics_busy')
    capacity_gate(con, evidence, snapshot.bytes)
    con.execute(MIGRATION.read_text(), prepare=False)
    meta = con.execute('SELECT snapshot_identity,snapshot_scope,snapshot_row_count,'
                       'snapshot_taken_at,snapshot_gate_version FROM raw.snapshot_meta FOR UPDATE').fetchall()
    if len(meta) > 1:
        raise GateError('metadata_grain')
    previous = meta[0][:4] if meta and meta[0][0] is not None else None
    if previous and meta[0][4] != VERSION:
        raise GateError('gate_version_changed')
    validate_count(snapshot, previous, baseline)
    # Preserve relation OID and dependent dbt views. DELETE and COPY are atomic;
    # readers see the old committed snapshot until the entire transaction commits.
    con.execute('DELETE FROM raw.churches')
    with con.cursor().copy('COPY raw.churches (' + ','.join(FIELDS) + ') FROM STDIN') as cp:
        for row in snapshot.rows:
            cp.write_row(row)
    con.execute('DELETE FROM raw.snapshot_meta')
    con.execute('INSERT INTO raw.snapshot_meta '
                '(snapshot_source,snapshot_taken_at,loaded_at,snapshot_identity,'
                'snapshot_scope,snapshot_row_count,snapshot_sha256,snapshot_gate_version) '
                'VALUES (%s,%s,now(),%s,%s,%s,%s,%s)',
                (VIEW, snapshot.taken_at, snapshot.identity, snapshot.scope,
                 len(snapshot.rows), snapshot.sha256, VERSION))


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
            p.add_argument('--apply', action='store_true')
            p.add_argument('--baseline', type=Path)
            p.add_argument('--capacity-evidence', type=Path)
            p.add_argument('--report', type=Path, required=True)
            args = p.parse_args(argv)
            # Reserve report before remote work; don't overwrite earlier evidence.
            fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as report:
                snapshot = capture(os.environ['PROD_READONLY_DATABASE_URL'])
                result = {'identity': snapshot.identity, 'scope': snapshot.scope,
                          'database_identity': snapshot.database, 'gate_version': VERSION,
                          'expected_rows': len(snapshot.rows), 'sha256': snapshot.sha256,
                          'taken_at': snapshot.taken_at.isoformat(), 'bytes': snapshot.bytes,
                          'applied': False}
                if args.apply:
                    with connect(os.environ['ANALYTICS_DATABASE_URL']) as con:
                        install(con, snapshot, load_json(args.baseline), load_json(args.capacity_evidence))
                    result['applied'] = True
                json.dump(result, report)
        print(json.dumps({'step': 'cloud_snapshot', 'status': 'ok',
                          'rows': len(snapshot.rows), 'applied': args.apply}))
        return 0
    except Exception:
        print('{"step":"cloud_snapshot","status":"failed"}')
        return 1
    finally:
        logging.disable(previous_logging)


if __name__ == '__main__':
    sys.exit(main())
