"""Local-only capture/download/compare. Reports contain private file identities."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path, PurePosixPath

from scripts.muse_shadow import PREFIX, file_report, database_counts, write_json
from scripts.muse_state_store import MAX_FILE, MAX_FILES, MAX_TOTAL, MAX_MANIFEST, digest, manifest_key


def download(store, run_id, destination):
    manifest_key(run_id)
    if destination.exists():
        raise ValueError('destination must be new')
    entries = json.loads(store.get(f'{PREFIX}/{run_id}/manifest.json', MAX_MANIFEST))
    if not isinstance(entries, list) or len(entries) > MAX_FILES:
        raise ValueError('invalid archive')
    seen, total = set(), 0
    for e in entries:
        name = e['path']
        p = PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name or str(p) != name or name in seen:
            raise ValueError('invalid archive path')
        seen.add(name)
        if type(e['bytes']) is not int or not 0 <= e['bytes'] <= MAX_FILE:
            raise ValueError('invalid archive size')
        total += e['bytes']
    if total > MAX_TOTAL:
        raise ValueError('archive too large')
    destination.mkdir(mode=0o700, parents=True)
    for e in entries:
        data = store.get(f"{PREFIX}/{run_id}/{e['path']}", e['bytes'])
        if len(data) != e['bytes'] or digest(data) != e['sha256']:
            raise ValueError('archive integrity failure')
        path = destination / e['path']
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as out:
            os.chmod(path, 0o600)
            out.write(data)


def received_delta(before, after):
    old = Counter(json.dumps(r, sort_keys=True) for r in before)
    new = Counter(json.dumps(r, sort_keys=True) for r in after)
    return {'added': [json.loads(r) for r in (new - old).elements()],
            'removed_or_replaced': [json.loads(r) for r in (old - new).elements()]}


def compare(before, shadow, local):
    unexplained, expected, context = {}, {}, []
    package_changes = {}
    for wp in sorted(set(before['packages']) | set(shadow['packages']) | set(local['packages'])):
        b, s, l = (x['packages'].get(wp, {}) for x in (before, shadow, local))
        package_changes[wp] = {'before': b, 'shadow': s, 'local': l}
        # Keep timestamps/notes visible in the private diff; don't silently normalize them.
        if s != l:
            if (s.get('state') in {'pending_build', 'build_failed'} and l.get('state') == 'ingested'
                    and shadow.get('status') == 'ok' and s.get('done_sha256') == l.get('done_sha256')):
                expected[wp] = 'shadow pull --no-build retains pre-build state; inspect remaining fields'
                ignored = {'state', 'ingested_at', 'build_error'}
                if {k:v for k,v in s.items() if k not in ignored} != {k:v for k,v in l.items() if k not in ignored}:
                    unexplained[wp] = 'additional package field differences'
            else:
                unexplained[wp] = 'package fields differ'
    deltas = {name: received_delta(before['received'], x['received'])
              for name, x in [('shadow', shadow), ('local', local)]}
    if deltas['shadow'] != deltas['local']:
        unexplained['received'] = deltas
    for key in ('seed_sha256', 'recheck_verdicts'):
        if shadow[key] != local[key]:
            unexplained[key] = {'shadow': shadow[key], 'local': local[key]}
    sc, lc = shadow.get('counts', {}), local.get('counts', {})
    if sc.get('directory_rows') == 134377 and lc.get('directory_rows') == 133939:
        expected['directory_rows'] = {'shadow': 134377, 'local': 133939,
                                     'reason': 'production versus May SQLite snapshot'}
        context.append('Other mart differences are NOT automatically explained by the 438-row directory gap; adjudicate them.')
    for key in sorted(set(sc) | set(lc)):
        if sc.get(key) != lc.get(key) and key not in expected:
            unexplained['counts.' + key] = {'shadow': sc.get(key), 'local': lc.get(key)}
    if shadow.get('status') != 'ok' or not sc or not lc:
        unexplained['incomplete'] = 'failed run or missing database counts'
    return {'unexplained': unexplained, 'expected': expected, 'context': context,
            'package_changes': package_changes, 'received_deltas': deltas,
            'limit': 'Compare only the same delivery cutoff, code, initial state and as_of_date; hashes alone do not adjudicate semantics.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('download')
    d.add_argument('--run-id', required=True)
    d.add_argument('--destination', type=Path, required=True)
    c = sub.add_parser('capture')
    c.add_argument('--root', type=Path, required=True)
    c.add_argument('--output', type=Path, required=True)
    c.add_argument('--drive', type=Path, required=True, help='Local Drive mirror for input identity comparison')
    c.add_argument('--as-of-date', required=True, help='Actual date used for the local dbt build')
    a = sub.add_parser('compare')
    a.add_argument('--shadow', type=Path, required=True)
    a.add_argument('--local', type=Path, required=True)
    a.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    if args.command == 'download':
        if os.environ.get('R2_PRIVATE_CONFIRMED') != 'true':
            raise ValueError('private store required')
        from backend.scrapers_v2.r2 import R2Client
        from scripts.muse_state_store import Store
        r2 = R2Client()
        download(Store(r2._ensure(), r2.bucket), args.run_id, args.destination)
    elif args.command == 'capture':
        from psycopg.conninfo import conninfo_to_dict
        url = os.environ['ANALYTICS_DATABASE_URL']
        info = conninfo_to_dict(url)
        if (info.get('host') not in {'localhost', '127.0.0.1', '::1'} or
                set(info) - {'host', 'port', 'user', 'password', 'dbname', 'sslmode'}):
            raise ValueError('local sidecar required')
        import subprocess
        report = file_report(args.root)
        delivery = {}
        total = 0
        for path in sorted((args.drive / 'returns').glob('WP-[0-9][0-9][0-9][0-9]/**/*')):
            if path.is_symlink():
                raise ValueError('unsafe local delivery')
            if not path.is_file():
                continue
            before = path.stat()
            if before.st_size > MAX_FILE or len(delivery) >= MAX_FILES:
                raise ValueError('local delivery limit')
            data = path.read_bytes()
            after = path.stat()
            total += len(data)
            if total > MAX_TOTAL or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('local delivery changed or too large')
            delivery[path.relative_to(args.drive).as_posix()] = {'sha256': digest(data), 'mtime': after.st_mtime}
        report['delivery'] = delivery
        report.update(counts=database_counts(args.root, url, disposable=False),
                      revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=args.root).decode().strip(),
                      as_of_date=args.as_of_date)
        write_json(args.output, report)
    else:
        shadow = json.loads((args.shadow / 'after.json').read_text())
        local = json.loads(args.local.read_text())
        result = compare(json.loads((args.shadow / 'before.json').read_text()), shadow, local)
        inputs = json.loads((args.shadow / 'inputs.json').read_text())
        receipt = args.shadow / 'private/dbt/accepted.json'
        accepted = json.loads(receipt.read_text()) if receipt.exists() else {}
        from datetime import datetime
        shadow_delivery = {name: {'sha256': entry['sha256'], 'mtime': datetime.fromisoformat(
            entry['modified_at'].replace('Z', '+00:00')).timestamp()}
            for name, entry in inputs['drive']['files'].items()}
        if shadow_delivery != local.get('delivery'):
            result['unexplained']['delivery_inputs'] = 'Local/Drive file hashes, modification times or file inventory differ'
        if inputs['drive']['oversized_files']:
            result['unexplained']['oversized_inputs'] = inputs['drive']['oversized_files']
        if local.get('revision') != inputs['revision'] or local.get('as_of_date') != accepted.get('as_of_date'):
            result['unexplained']['versions'] = 'code revision or dbt as_of_date differs'
        write_json(args.output, result)
        print(json.dumps({'step': 'compare', 'status': 'different' if result['unexplained'] else 'ok',
                          'differences': len(result['unexplained'])}))
        return int(bool(result['unexplained']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
