"""Read-only publication eligibility. No apply path exists in this module.

Decisions are at church-row grain: one replacement blocks that whole row.
Private field evidence is copied from the exact publisher plan, never rebuilt.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import math
from zoneinfo import ZoneInfo

from scripts.publish_verified import COLUMNS, _blank

REASONS = frozenset({
    'replace', 'coordinate_move_gt_50m', 'invalid_change', 'possible_match',
    'low_match_confidence', 'shared_address', 'identity_evidence_missing',
    'auto_limit', 'd1_write',
    'stale_as_of_date', 'revert_since_publish', 'dbt_not_passed',
    'read_only', 'health_unavailable',
})


def normalized(value):
    return ' '.join(str(value or '').split()).casefold()


def distance_m(old, new):
    """Great-circle distance, with coordinates in (latitude, longitude)."""
    a, b = map(math.radians, old)
    c, d = map(math.radians, new)
    h = math.sin((c-a)/2)**2 + math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def evaluate(plan, run_results, as_of_date, publish_log, health, *, now=None):
    """Pure gate; caller supplies read-only observations from this exact run.

    publish_log is ordered by its monotonic id, not client clocks. A revert
    after the latest insert/update blocks; a subsequent publication resets it.
    Missing/invalid health is distinct from an explicit READ_ONLY response.
    """
    now = now or datetime.now(ZoneInfo('America/Los_Angeles'))
    global_reasons = set()
    if as_of_date != now.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat():
        global_reasons.add('stale_as_of_date')
    results = run_results.get('results') if isinstance(run_results, dict) else None
    if not isinstance(results, list) or not results or any(
            not isinstance(r, dict) or r.get('status') not in {'success', 'pass'} for r in results):
        global_reasons.add('dbt_not_passed')
    if not isinstance(health, dict) or type(health.get('read_only')) is not bool:
        global_reasons.add('health_unavailable')
    elif health['read_only']:
        global_reasons.add('read_only')
    last_publish = max((r['id'] for r in publish_log if r['action'] in {'insert', 'update'}), default=-1)
    if any(r['action'] == 'revert' and r['id'] > last_publish for r in publish_log):
        global_reasons.add('revert_since_publish')

    addresses = defaultdict(list)
    for i, p in enumerate(plan):
        if p['kind'] == 'insert':
            row = p['row']
            key = tuple(normalized(row.get(k)) for k in ('address', 'city', 'state', 'zip_code'))
            if key[0]:
                addresses[key].append((i, normalized(row.get('name'))))
    collisions = {i for group in addresses.values() if len({name for _, name in group}) > 1 for i, _ in group}
    decisions = []
    for i, p in enumerate(plan):
        reasons = set()
        changes = p['changes']
        if p['kind'] not in {'insert', 'update'} or not changes:
            reasons.add('invalid_change')
        for field, action, old, new in changes:
            if field not in COLUMNS or action not in {'fill', 'replace'} or _blank(new):
                reasons.add('invalid_change')
            if action == 'replace' or not _blank(old):
                reasons.add('replace')
        row = p['row']
        if p['kind'] == 'insert':
            keys = ('possible_match_church_id', 'possible_match_candidate_id', 'match_confidence')
            if any(k not in row for k in keys):
                reasons.add('identity_evidence_missing')
            if any(not _blank(row.get(k)) for k in keys[:2]):
                reasons.add('possible_match')
            if normalized(row.get('match_confidence')) == 'low':
                reasons.add('low_match_confidence')
            if i in collisions:
                reasons.add('shared_address')
        changed_coords = {f: (old, new) for f, _, old, new in changes
                          if f in {'latitude', 'longitude'}}
        prior = p.get('current', {})
        coords = {f: changed_coords.get(f, (prior.get(f), prior.get(f)))
                  for f in ('latitude', 'longitude')}
        if changed_coords and all(not _blank(v) for pair in coords.values() for v in pair):
            movement = distance_m((float(coords['latitude'][0]), float(coords['longitude'][0])),
                                  (float(coords['latitude'][1]), float(coords['longitude'][1])))
            if movement > 50 and not math.isclose(movement, 50, abs_tol=1e-8):
                reasons.add('coordinate_move_gt_50m')
        # Owner decision 2026-11-06: phone evidence must not veto publication.
        # Upstream display/withholding rules are unchanged. Any D-1 write vetoes the run.
        if any(f in {'scope_status', 'display_tradition'} for f, _, _, _ in changes):
            global_reasons.add('d1_write')
        decisions.append({'kind': p['kind'], 'subject': p['subject'], 'church_id': p['church_id'],
                          'changes': changes, 'prior_coordinates': {k: prior.get(k) for k in ('latitude', 'longitude')},
                          'evidence': {k: row.get(k) for k in (
                              'possible_match_church_id', 'possible_match_candidate_id',
                              'match_confidence', 'personal_phone_withheld',
                              'name', 'address', 'city', 'state', 'zip_code')},
                          'reasons': sorted(reasons)})
    if sum(not r['reasons'] for r in decisions) > 200:
        global_reasons.add('auto_limit')
    for r in decisions:
        r['reasons'] = sorted(set(r['reasons']) | global_reasons)
        r['decision'] = 'pending' if r['reasons'] else 'auto'
    counts = Counter(reason for r in decisions for reason in r['reasons'])
    auto = sum(r['decision'] == 'auto' for r in decisions)
    summary = {'publish_auto_rows': auto, 'publish_pending_rows': len(decisions)-auto,
               'publish_gate': 'pending' if global_reasons or auto != len(decisions) else 'auto_eligible',
               **{'publish_reason_' + reason: counts[reason] for reason in sorted(REASONS)}}
    return {'rows': decisions, 'summary': summary, 'run_reasons': sorted(global_reasons)}


def fetch_health(base_url):
    """Bounded GET; never forward credentials or follow redirects."""
    import requests
    try:
        response = requests.get(base_url.rstrip('/') + '/api/health', timeout=15, allow_redirects=False)
        if response.status_code != 200:
            return None
        value = response.json()
        return value if isinstance(value, dict) and type(value.get('read_only')) is bool else None
    except (requests.RequestException, ValueError, AttributeError):
        return None


def dry_run(directory, receipt_path, results_path):
    """One read-only production snapshot supplies both plan and revert history."""
    import json
    import os
    import uuid
    import psycopg
    from psycopg.rows import dict_row
    from scripts import publish_verified as publisher
    from scripts.muse_shadow import write_json

    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt = json.loads(receipt_path.read_text())
    results = json.loads(results_path.read_text())
    with psycopg.connect(os.environ['ANALYTICS_DATABASE_URL'], prepare_threshold=None) as ana:
        ana.execute('SET TRANSACTION READ ONLY')
        churches, new = publisher.load_marts(ana)
        # Evidence-only association: do not change marts' business predicates.
        with ana.cursor(row_factory=dict_row) as cur:
            candidates = {r['candidate_id']: r for r in cur.execute(
                'SELECT candidate_id, possible_match_church_id, possible_match_candidate_id, '
                'match_confidence, personal_phone_withheld FROM analytics.stg_muse_candidates').fetchall()}
            existing = {r['church_id']: r for r in cur.execute(
                'SELECT church_id, personal_phone_withheld FROM analytics.stg_muse_results').fetchall()}
        for row in churches:
            row.update({k: v for k, v in existing.get(row['church_id'], {}).items() if k != 'church_id'})
        for row in new:
            row.update({k: v for k, v in candidates.get(row['external_id'], {}).items() if k != 'candidate_id'})
    with psycopg.connect(os.environ['PUBLISH_DATABASE_URL'], prepare_threshold=None) as prod:
        prod.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        prod.execute("SET LOCAL search_path = pg_catalog, public")
        prod.execute("SET LOCAL statement_timeout = '60s'")
        publisher.check_schema(prod)
        plan = publisher.build_plan(prod, churches, new)
        with prod.cursor(row_factory=dict_row) as cur:
            logs = cur.execute('SELECT id, action FROM public.publish_log ORDER BY id').fetchall()
    run_id = 'pub-' + uuid.uuid4().hex
    diff = publisher.write_diff(plan, run_id, directory)
    health = fetch_health(os.environ.get('BACKEND_URL', ''))
    observed_at = datetime.now(timezone.utc)
    decision = evaluate(plan, results, receipt.get('as_of_date'), logs, health, now=observed_at)
    # Exact bytes bind the CSV and adjudication; the enclosing archive hashes all files.
    from scripts.muse_state_store import digest
    write_json(directory / 'rows.json', {'run_id': run_id, 'diff_sha256': digest(diff.read_bytes()),
               'rows': decision['rows']})
    write_json(directory / 'run.json', {'run_id': run_id, 'as_of_date': receipt.get('as_of_date'),
               'diff_sha256': digest(diff.read_bytes()), 'receipt_sha256': digest(receipt_path.read_bytes()),
               'dbt_results_sha256': digest(results_path.read_bytes()),
               'observed_at': observed_at.isoformat(),
               'publish_log': logs, 'health': health, 'run_reasons': decision['run_reasons'],
               'summary': decision['summary']})
    return decision['summary']


def main(argv=None):
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--private-dir', required=True, type=Path)
    ap.add_argument('--receipt', required=True, type=Path)
    ap.add_argument('--run-results', required=True, type=Path)
    args = ap.parse_args(argv)
    summary = dry_run(args.private_dir, args.receipt, args.run_results)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
