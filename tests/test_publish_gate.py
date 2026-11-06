from datetime import datetime, timezone
import math

import pytest
from scripts.publish_gate import evaluate, distance_m

NOW = datetime(2026, 11, 6, 8, tzinfo=timezone.utc)


def entry(i=1, **row):
    return {'kind': 'insert', 'subject': str(i), 'church_id': None,
            'changes': [('name', 'fill', None, 'Private Name')],
            'row': {'name': 'Private Name', 'address': f'{i} Main', 'city': 'City',
                    'state': 'CA', 'zip_code': '94000', 'possible_match_church_id': None,
                    'possible_match_candidate_id': None, 'match_confidence': 'high', **row}}


def gate(plan=None, **kw):
    args = dict(plan=[entry()] if plan is None else plan,
                run_results={'results': [{'status': 'success'}, {'status': 'pass'}]},
                as_of_date='2026-11-06', publish_log=[], health={'read_only': False},
                now=NOW)
    return evaluate(**(args | kw))


def test_fill_passes_and_replacement_blocks_whole_row():
    assert gate()['rows'][0]['decision'] == 'auto'
    p = entry()
    p['changes'].append(('phone', 'replace', 'old', 'new'))
    result = gate([p, entry(2)])
    assert [r['decision'] for r in result['rows']] == ['pending', 'auto']
    assert result['rows'][0]['changes'] == p['changes']


@pytest.mark.parametrize('size,expected', [(200, 'auto_eligible'), (201, 'pending')])
def test_auto_limit(size, expected):
    result = gate([entry(i) for i in range(size)])
    assert result['summary']['publish_gate'] == expected
    assert result['summary']['publish_pending_rows'] == (size if size > 200 else 0)


def test_limit_counts_only_row_eligible_subset():
    result = gate([entry(i) for i in range(200)] + [entry(300, match_confidence='low')])
    assert result['summary']['publish_auto_rows'] == 200
    assert 'auto_limit' not in result['run_reasons']


@pytest.mark.parametrize('override,reason', [
    ({'as_of_date': '2026-11-05'}, 'stale_as_of_date'),
    ({'run_results': {'results': [{'status': 'warn'}]}}, 'dbt_not_passed'),
    ({'run_results': {}}, 'dbt_not_passed'),
    ({'health': None}, 'health_unavailable'),
    ({'health': {'read_only': 'false'}}, 'health_unavailable'),
    ({'health': {'read_only': True}}, 'read_only'),
    ({'publish_log': [{'id': 1, 'action': 'insert'}, {'id': 2, 'action': 'revert'}]}, 'revert_since_publish'),
])
def test_run_conditions(override, reason):
    result = gate([entry(1), entry(2)], **override)
    assert all(reason in r['reasons'] and r['decision'] == 'pending' for r in result['rows'])
    assert gate()['summary']['publish_gate'] == 'auto_eligible'


def test_later_publication_and_pacific_midnight():
    assert gate(publish_log=[{'id': 1, 'action': 'revert'}, {'id': 2, 'action': 'update'}])['run_reasons'] == []
    assert gate(now=datetime(2026, 11, 6, 7, 59, tzinfo=timezone.utc))['run_reasons'] == ['stale_as_of_date']


@pytest.mark.parametrize('row,reason', [
    ({'possible_match_church_id': 1}, 'possible_match'),
    ({'possible_match_candidate_id': 'candidate'}, 'possible_match'),
    ({'match_confidence': 'low'}, 'low_match_confidence'),
])
def test_identity(row, reason):
    result = gate([entry(1, **row), entry(2)])
    assert reason in result['rows'][0]['reasons']
    assert result['rows'][1]['decision'] == 'auto'


def test_shared_address_blocks_both():
    result = gate([entry(1, name='One'), entry(2, address=' 1 MAIN ', name='Two'), entry(3)])
    assert [r['decision'] for r in result['rows']] == ['pending', 'pending', 'auto']
    assert all('shared_address' in r['reasons'] for r in result['rows'][:2])


@pytest.mark.parametrize('meters', [50, 51])
def test_coordinate_boundary(meters):
    lat = math.degrees(meters / 6371000)
    assert distance_m((0, 0), (lat, 0)) == pytest.approx(meters)
    p = entry()
    p['kind'] = 'update'
    p['current'] = {'latitude': 0, 'longitude': 0}
    p['changes'] = [('latitude', 'replace', 0, lat)]
    result = gate([p])['rows'][0]
    assert result['decision'] == 'pending' and 'replace' in result['reasons']
    assert ('coordinate_move_gt_50m' in result['reasons']) == (meters > 50)


def test_health_failure_closed(monkeypatch):
    import requests
    from scripts.publish_gate import fetch_health
    def fail(*args, **kwargs):
        raise requests.Timeout('private URL and credentials')
    monkeypatch.setattr(requests, 'get', fail)
    assert fetch_health('https://private.example') is None
    assert gate(health=fetch_health('https://private.example'))['run_reasons'] == ['health_unavailable']


def test_real_readonly_dry_run_private_evidence(tmp_path, monkeypatch, capsys):
    import csv
    import json
    import os
    import psycopg
    from scripts import publish_gate as g
    if not os.environ.get('DATABASE_URL'):
        pytest.skip('isolated Postgres DATABASE_URL required')
    url = os.environ['DATABASE_URL']
    assert '127.0.0.1:55493/churchmap_publisher_test' in url or 'test' in url
    with psycopg.connect(url, autocommit=True) as con:
        # All fixtures are isolated; refuse to reuse any real analytics schema.
        con.execute('CREATE SCHEMA analytics')
        # check_visibility refuses an empty directory, which production never is.
        directory_id = con.execute("INSERT INTO churches (name, source) VALUES ('Gate directory fixture', 'osm') "
                                   "RETURNING church_id").fetchone()[0]
        try:
            con.execute('CREATE TABLE analytics.mart_publish_churches (church_id bigint)')
            con.execute('CREATE TABLE analytics.mart_publish_new (external_id text, name text, address text)')
            con.execute("INSERT INTO analytics.mart_publish_new VALUES ('gate-private', 'Private Name', '1 Private Street')")
            con.execute('CREATE TABLE analytics.stg_muse_results (church_id bigint, personal_phone_withheld text)')
            con.execute('CREATE TABLE analytics.stg_muse_candidates (candidate_id text, possible_match_church_id bigint, possible_match_candidate_id text, match_confidence text, personal_phone_withheld text)')
            con.execute("INSERT INTO analytics.stg_muse_candidates VALUES ('gate-private', NULL, NULL, 'high', 'no')")
            monkeypatch.setenv('PUBLISH_DATABASE_URL', url)
            monkeypatch.setenv('ANALYTICS_DATABASE_URL', url)
            monkeypatch.setattr(g, 'fetch_health', lambda _: None)
            receipt, results = tmp_path / 'receipt.json', tmp_path / 'run_results.json'
            receipt.write_text(json.dumps({'as_of_date': '2026-11-06'}))
            results.write_text(json.dumps({'results': [{'status': 'pass'}]}))
            directory = tmp_path / 'private'
            summary = g.dry_run(directory, receipt, results)
            assert summary['publish_gate'] == 'pending'
            assert summary['publish_reason_health_unavailable'] == 1
            assert not con.execute("SELECT 1 FROM churches WHERE external_id='gate-private'").fetchone()
            row_report = json.loads((directory / 'rows.json').read_text())
            diff = list(csv.DictReader(next(directory.glob('publish_diff_*.csv')).open()))
            assert len(diff) == len(row_report['rows'][0]['changes']) == 2
            assert [(r['field'], r['new_value']) for r in diff] == [(c[0], c[3]) for c in row_report['rows'][0]['changes']]
            assert capsys.readouterr().out == ''
        finally:
            con.execute('DROP SCHEMA analytics CASCADE')
            con.execute('DELETE FROM churches WHERE church_id = %s', (directory_id,))


@pytest.mark.parametrize('field', ['scope_status', 'display_tradition'])
def test_d1_write_blocks_whole_run(field):
    p = entry()
    p['changes'].append((field, 'fill', None, 'pending'))
    result = gate([p, entry(2)])
    assert result['run_reasons'] == ['d1_write']
    assert result['summary']['publish_auto_rows'] == 0
    assert all('d1_write' in r['reasons'] for r in result['rows'])
    assert gate()['summary']['publish_gate'] == 'auto_eligible'


@pytest.mark.parametrize('withheld', ['yes', 'no', True, False, None])
def test_owner_phone_exception_does_not_veto(withheld):
    p = entry(personal_phone_withheld=withheld)
    p['changes'].append(('phone', 'fill', None, '6505550100'))
    assert gate([p])['summary']['publish_gate'] == 'auto_eligible'
