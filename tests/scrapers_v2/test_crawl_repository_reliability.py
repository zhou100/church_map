"""Real SQL regression coverage, run by tests.yml's isolated Postgres service."""
import asyncio
import os
from uuid import uuid4

import pytest

from backend.db.repository import CrawlBusy, CrawlRepository, StatsRepository

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='needs isolated test Postgres')


def db_test(body):
    from psycopg import AsyncConnection

    async def go():
        async with await AsyncConnection.connect(os.environ['DATABASE_URL']) as con:
            try:
                return await body(con, CrawlRepository(con))
            finally:
                await con.rollback()
    return asyncio.run(go())


async def church(con):
    row = await (await con.execute(
        "INSERT INTO churches (name, website, extracted_at, extracted_prompt_version, extracted_model, "
        "website_summary) VALUES ('reliability fixture', 'https://fixture.test/', NOW(), 'old', 'old', "
        "'keep this result') RETURNING church_id",
    )).fetchone()
    return row[0]


async def artifact(repo, cid, **kw):
    args = dict(church_id=cid, url='https://fixture.test/', kind='homepage', http_status=200,
                fetch_error=None, robots_allowed=True, content_hash='fixture-hash',
                r2_key='fixture-key', bytes_raw=100, bytes_text=50, crawl_run_id=None)
    args.update(kw)
    return await repo.insert_artifact(**args)


def test_invalid_pending_cannot_block_requeue_or_claim_a_queue_slot():
    async def body(con, repo):
        cid = await church(con)
        good = await artifact(repo, cid)
        await con.execute("UPDATE raw_crawl_artifacts SET extract_status='ok' WHERE id=%s", (good,))
        bad = await artifact(repo, cid, url='https://fixture.test/failure', content_hash=None,
                             r2_key=None, http_status=0, fetch_error='timeout')
        # New failed fetches start skipped. Also seed the historical bug.
        row = await (await con.execute('SELECT extract_status FROM raw_crawl_artifacts WHERE id=%s', (bad,))).fetchone()
        assert row[0] == 'skipped'
        await con.execute("UPDATE raw_crawl_artifacts SET extract_status='pending' WHERE id=%s", (bad,))
        before = await repo.count_stale_extractions('new', 'new')
        assert before['awaiting_queue'] >= 1
        assert cid in await repo.requeue_stale_extractions('new', 'new', limit=10000)
        target = next(t for t in await repo.pending_extract_targets(10000) if t['church_id'] == cid)
        assert target['artifact_ids'] == [good]
        assert (await repo.count_stale_extractions('new', 'new'))['awaiting_queue'] == before['awaiting_queue'] - 1
        assert (await StatsRepository(con).crawl_health())['queue']['invalid_pending'] >= 1
    db_test(body)


@pytest.mark.parametrize('status,detail,expected', [
    ('pending', None, 'pending'), ('ok', None, 'ok'),
    ('skipped', 'no-html:1/1', 'pending'), ('skipped', 'no-text', 'skipped'),
    ('error', 'bad model output', 'error'),
])
def test_same_content_refetch_repairs_storage_without_resetting_results(status, detail, expected):
    async def body(con, repo):
        cid = await church(con)
        aid = await artifact(repo, cid)
        await con.execute(
            "UPDATE raw_crawl_artifacts SET r2_key=NULL, extract_status=%s, "
            "extract_error_detail=%s, fetched_at=NOW()-INTERVAL '60 days' WHERE id=%s",
            (status, detail, aid),
        )
        assert await artifact(repo, cid, r2_key='restored-key') == aid
        row = await (await con.execute(
            'SELECT r2_key, extract_status, extract_error_detail, fetched_at > NOW()-INTERVAL \'1 day\' '
            'FROM raw_crawl_artifacts WHERE id=%s', (aid,),
        )).fetchone()
        assert row[:2] == ('restored-key', expected)
        assert row[2] == (None if detail and detail.startswith('no-html:') else detail)
        assert row[3]
        saved = await (await con.execute('SELECT website_summary, extracted_model FROM churches WHERE church_id=%s', (cid,))).fetchone()
        assert saved == ('keep this result', 'old')
        # Same page is still a single artifact; no accidental paid re-extraction.
        target = [t for t in await repo.pending_extract_targets(10000) if t['church_id'] == cid]
        assert bool(target) == (expected == 'pending')
    db_test(body)


def test_invalid_ok_artifacts_cannot_be_requeued():
    async def body(con, repo):
        cid = await church(con)
        aid = await artifact(repo, cid)
        await con.execute("UPDATE raw_crawl_artifacts SET extract_status='ok', r2_key='' WHERE id=%s", (aid,))
        assert cid not in await repo.requeue_stale_extractions('new', 'new', limit=10000)
    db_test(body)


@pytest.mark.parametrize('restored_key', ['new-restored-key', 'old-missing-key'])
def test_stale_missing_key_observation_cannot_undo_concurrent_repair(restored_key):
    async def body(con, repo):
        cid = await church(con)
        aid = await artifact(repo, cid, r2_key='old-missing-key')
        target = next(t for t in await repo.pending_extract_targets(10000) if t['church_id'] == cid)
        await artifact(repo, cid, r2_key=restored_key)
        updated = await repo.mark_artifacts_status(
            [aid], status='skipped', error_detail='no-html:1/1', expected_r2_keys=['old-missing-key'],
            expected_fetched_ats=target['fetched_ats'],
        )
        assert updated == 0
        row = await (await con.execute(
            'SELECT r2_key, extract_status FROM raw_crawl_artifacts WHERE id=%s', (aid,),
        )).fetchone()
        assert row == (restored_key, 'pending')
        # A genuine missing observation about the unchanged key still works.
        target = next(t for t in await repo.pending_extract_targets(10000) if t['church_id'] == cid)
        assert await repo.mark_artifacts_status(
            [aid], status='skipped', error_detail='no-html:1/1', expected_r2_keys=[restored_key],
            expected_fetched_ats=target['fetched_ats'],
        ) == 1
    db_test(body)


def test_no_text_200_does_not_make_a_church_fresh():
    async def body(con, repo):
        cid = await church(con)
        aid = await artifact(repo, cid, r2_key=None, content_hash=None, fetch_error='no-text')
        # NOW() is fixed within this fixture transaction. Put the attempt
        # strictly before it so the test isolates freshness from backoff.
        await con.execute(
            "UPDATE raw_crawl_artifacts SET fetched_at=NOW()-INTERVAL '1 hour' WHERE id=%s", (aid,),
        )
        due = await repo.churches_due_for_fetch(10000, 30, failure_backoff_hours=0)
        assert cid in {r['church_id'] for r in due}
    db_test(body)


def test_lease_duplicate_replay_and_expiry_preserve_committed_progress():
    from psycopg import AsyncConnection

    async def go():
        one = await AsyncConnection.connect(os.environ['DATABASE_URL'])
        two = await AsyncConnection.connect(os.environ['DATABASE_URL'])
        ids = []
        key = str(uuid4())
        try:
            r1, r2 = CrawlRepository(one), CrawlRepository(two)
            first, replay = await r1.claim_run('fetch', 5, key, lease_seconds=540)
            ids.append(first['id'])
            assert not replay
            await r1.update_run_progress(first['id'], dict(rows_ok=1, rows_error=0, rows_processed=1))
            await one.commit()
            with pytest.raises(CrawlBusy):
                await r2.claim_run('fetch', 5, key + '-other', lease_seconds=540)
            await two.rollback()
            same, replay = await r2.claim_run('fetch', 5, key, lease_seconds=540)
            await two.commit()
            assert replay and same['id'] == first['id'] and same['rows_ok'] == 1
            await one.execute("UPDATE crawl_stage_leases SET expires_at=NOW()-INTERVAL '1 second' WHERE stage='fetch'")
            await one.commit()
            same, replay = await r2.claim_run('fetch', 5, key, lease_seconds=540)
            await two.commit()
            assert replay and same['status'] == 'error' and same['rows_ok'] == 1
            second, replay = await r2.claim_run('fetch', 5, key + '-next', lease_seconds=540)
            ids.append(second['id'])
            await two.commit()
            assert not replay
            dead = await (await one.execute('SELECT status, rows_ok, progress_at FROM crawl_runs WHERE id=%s', (first['id'],))).fetchone()
            assert dead[0:2] == ('error', 1)
            assert dead[2] is not None
            # Completed/expired keys also replay; a lost HTTP response cannot
            # cause a second fetch of a different batch.
            same, replay = await r1.claim_run('fetch', 5, key, lease_seconds=540)
            assert replay and same['id'] == first['id']
        finally:
            await one.rollback()
            await two.rollback()
            await one.execute('UPDATE crawl_stage_leases SET run_id=NULL, expires_at=NULL WHERE run_id=ANY(%s)', (ids,))
            await one.execute('DELETE FROM crawl_runs WHERE id=ANY(%s)', (ids,))
            await one.commit()
            await one.close()
            await two.close()
    asyncio.run(go())
