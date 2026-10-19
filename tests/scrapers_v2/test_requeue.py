"""Re-queue semantics for the extraction backfill.

Runs against a real Postgres when DATABASE_URL is set — this code mutates
the extract queue, and its two counters mean subtly different things, which
is exactly the kind of thing mocks agree with and databases don't.

Driven with asyncio.run rather than pytest-asyncio/anyio: the suite has no
async plugin, and an async test without one is silently *skipped* — a test
that proves nothing while looking like it passed. Each test opens its own
connection, seeds fixture rows, and rolls back, so nothing is left behind
even against a populated database.
"""
from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set; re-queue tests need a real Postgres",
)

CURRENT_VERSION = "test.v9"
CURRENT_MODEL = "test/model-new"
OLD_MODEL = "test/model-old"

# (extracted_prompt_version, extracted_model, artifact extract_status)
SEED = [
    ("stale prompt", "test.v1",       CURRENT_MODEL, "ok"),
    ("stale model",  CURRENT_VERSION, OLD_MODEL,     "ok"),
    ("current",      CURRENT_VERSION, CURRENT_MODEL, "ok"),
    ("never",        None,            None,          "pending"),
]


async def _seed(con) -> list[int]:
    from backend.db.repository import CrawlRepository  # noqa: F401  (import check)

    ids: list[int] = []
    async with con.cursor() as cur:
        for label, version, model, status in SEED:
            extracted_at = None if version is None and model is None else "NOW()"
            await cur.execute(
                f"""
                INSERT INTO churches
                    (name, website, extracted_at, extracted_prompt_version, extracted_model)
                VALUES (%s, %s, {extracted_at or 'NULL'}, %s, %s)
                RETURNING church_id
                """,
                (f"rq {label}", f"https://rq-{label.replace(' ', '-')}.test", version, model),
            )
            cid = (await cur.fetchone())[0]
            ids.append(cid)
            await cur.execute(
                """
                INSERT INTO raw_crawl_artifacts
                    (church_id, url, kind, content_hash, r2_key, http_status, extract_status)
                VALUES (%s, %s, 'homepage', %s, %s, 200, %s)
                """,
                (cid, f"https://rq{cid}.test", f"rqh{cid}", f"rqk{cid}", status),
            )
    return ids


def run_with_fixture(body):
    """Seed, run `body(repo, ids)`, always roll back."""
    from psycopg import AsyncConnection

    from backend.db.repository import CrawlRepository

    async def go():
        con = await AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            ids = await _seed(con)
            return await body(CrawlRepository(con), ids)
        finally:
            await con.rollback()
            await con.close()

    return asyncio.run(go())


def test_stale_covers_both_old_prompt_and_old_model():
    async def body(r, ids):
        counts = await r.count_stale_extractions(CURRENT_VERSION, CURRENT_MODEL)
        # Two seeded stale rows: one on an old prompt, one on an old model.
        # A never-extracted church is not "stale" — it was never done.
        assert counts["total"] >= 2

    run_with_fixture(body)


def test_requeue_skips_current_and_never_extracted():
    async def body(r, ids):
        stale_prompt, stale_model, current, never = ids
        got = set(await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=10_000))
        assert stale_prompt in got
        assert stale_model in got
        assert current not in got
        assert never not in got

    run_with_fixture(body)


def test_successive_passes_walk_forward():
    """Without skipping already-queued churches every pass re-targets the
    same lowest ids and the backfill never advances: a church stays stale
    until the extract stage rewrites its row, long after it was queued."""
    async def body(r, ids):
        first = set(await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=1))
        second = set(await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=1))
        assert len(first) == 1
        assert len(second) == 1
        assert first != second

    run_with_fixture(body)


def test_awaiting_queue_falls_but_total_does_not():
    """The distinction the endpoint reports: queueing work is not finishing
    it. `total` only drops once the extract stage rewrites the church row."""
    async def body(r, ids):
        before = await r.count_stale_extractions(CURRENT_VERSION, CURRENT_MODEL)
        await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=10_000)
        after = await r.count_stale_extractions(CURRENT_VERSION, CURRENT_MODEL)
        assert after["awaiting_queue"] < before["awaiting_queue"]
        assert after["total"] == before["total"]

    run_with_fixture(body)


def test_stale_church_with_nothing_requeueable_does_not_block():
    """A stale church whose artifacts all errored has nothing to put back.
    It must not consume a `limit` slot — it never gains a 'pending' artifact,
    so it would sit at the head of the queue on every pass and stall the
    backfill, with `awaiting_queue` stuck above zero forever."""
    async def body(r, ids):
        blocker, next_up = ids[0], ids[1]
        async with r.con.cursor() as cur:
            await cur.execute(
                "UPDATE raw_crawl_artifacts SET extract_status='error' WHERE church_id=%s",
                (blocker,),
            )
        got = set(await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=1))
        assert got == {next_up}, "the un-requeueable church swallowed the limit slot"

        counts = await r.count_stale_extractions(CURRENT_VERSION, CURRENT_MODEL)
        # blocker is still stale, but is not waiting on the queue for anything
        assert counts["total"] >= 2
        assert counts["awaiting_queue"] == 0

    run_with_fixture(body)


def test_stats_and_requeue_agree_on_what_is_stale():
    """Two code paths answer "how many churches need re-extracting?" — the
    public /api/stats endpoint and the re-queue. They must agree.

    They didn't: stats grouped on prompt version alone while the re-queue
    keys on version AND model, so a church on the current prompt but an old
    model showed as current in stats and was immediately picked up by the
    re-queue. The seed data below contains exactly that row.
    """
    from backend.db.repository import StatsRepository
    from backend.routers.stats import build_stats

    async def body(r, ids):
        stats_repo = StatsRepository(r.con)
        shaped = build_stats(
            await stats_repo.church_counts(),
            await stats_repo.extraction_by_prompt_version(),
            await stats_repo.crawl_health(),
            current_prompt_version=CURRENT_VERSION,
            current_model=CURRENT_MODEL,
        )
        requeue = await r.count_stale_extractions(CURRENT_VERSION, CURRENT_MODEL)
        assert shaped["extraction"]["stale"] == requeue["total"]

    run_with_fixture(body)


def test_errored_artifacts_are_left_alone():
    """An artifact that failed extraction will fail again on a new prompt;
    re-queueing it spends the same money to hit the same wall."""
    async def body(r, ids):
        stale_prompt = ids[0]
        async with r.con.cursor() as cur:
            await cur.execute(
                "UPDATE raw_crawl_artifacts SET extract_status = 'error' WHERE church_id = %s",
                (stale_prompt,),
            )
        got = set(await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=10_000))
        assert stale_prompt not in got

    run_with_fixture(body)


@pytest.mark.parametrize("http_status,r2_key", [(0, None), (200, None), (503, "bad/key")])
def test_unextractable_pending_fetch_does_not_block_requeue(http_status, r2_key):
    """A failed fetch defaults to pending, but cannot be consumed by extract."""
    async def body(r, ids):
        stale_prompt = ids[0]
        async with r.con.cursor() as cur:
            await cur.execute(
                """INSERT INTO raw_crawl_artifacts
                       (church_id, url, kind, http_status, r2_key)
                   VALUES (%s, 'https://failed.test/', 'homepage', %s, %s)""",
                (stale_prompt, http_status, r2_key),
            )
        counts = await r.count_stale_extractions(CURRENT_VERSION, CURRENT_MODEL)
        assert counts["awaiting_queue"] == 2
        got = set(await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=1))
        assert got == {stale_prompt}
        targets = await r.pending_extract_targets(limit=10)
        target = next(t for t in targets if t["church_id"] == stale_prompt)
        assert len(target["artifact_ids"]) == 1

    run_with_fixture(body)


@pytest.mark.parametrize("http_status,r2_key", [(0, None), (200, None), (503, "bad/key")])
def test_unusable_ok_artifact_does_not_swallow_requeue_slot(http_status, r2_key):
    async def body(r, ids):
        blocker, next_up = ids[:2]
        async with r.con.cursor() as cur:
            await cur.execute(
                "UPDATE raw_crawl_artifacts SET http_status=%s, r2_key=%s WHERE church_id=%s",
                (http_status, r2_key, blocker),
            )
        counts = await r.count_stale_extractions(CURRENT_VERSION, CURRENT_MODEL)
        assert counts["awaiting_queue"] == 1
        got = set(await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=1))
        assert got == {next_up}

    run_with_fixture(body)


def test_usable_pending_artifact_still_blocks_duplicate_requeue():
    async def body(r, ids):
        already_queued, next_up = ids[:2]
        async with r.con.cursor() as cur:
            await cur.execute(
                "UPDATE raw_crawl_artifacts SET extract_status='pending' WHERE church_id=%s",
                (already_queued,),
            )
        assert (await r.count_stale_extractions(CURRENT_VERSION, CURRENT_MODEL))["awaiting_queue"] == 1
        got = set(await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=1))
        assert got == {next_up}

    run_with_fixture(body)


def test_requeue_only_changes_usable_ok_artifacts():
    async def body(r, ids):
        cid = ids[0]
        async with r.con.cursor() as cur:
            await cur.execute(
                """INSERT INTO raw_crawl_artifacts
                       (church_id, url, kind, http_status, extract_status)
                   VALUES (%s, 'https://unusable.test/', 'about', 200, 'ok')
                   RETURNING id""",
                (cid,),
            )
            unusable_id = (await cur.fetchone())[0]
        got = await r.requeue_stale_extractions(CURRENT_VERSION, CURRENT_MODEL, limit=1)
        assert got == [cid]
        async with r.con.cursor() as cur:
            await cur.execute("SELECT extract_status FROM raw_crawl_artifacts WHERE id=%s", (unusable_id,))
            assert await cur.fetchone() == ("ok",)

    run_with_fixture(body)


@pytest.mark.parametrize("status", ["ok", "pending", "error", "skipped"])
def test_unchanged_refetch_refreshes_freshness_without_reextracting(status):
    """An unchanged homepage must leave the due queue without losing its state."""
    async def body(r, ids):
        cid = ids[0]
        async with r.con.cursor() as cur:
            await cur.execute(
                """UPDATE raw_crawl_artifacts
                      SET fetched_at=NOW() - INTERVAL '40 days', extract_status=%s,
                          extracted_at=NOW() - INTERVAL '39 days'
                    WHERE church_id=%s""",
                (status, cid),
            )
            await cur.execute(
                "SELECT id, extracted_at FROM raw_crawl_artifacts WHERE church_id=%s", (cid,)
            )
            artifact_id, extracted_at = await cur.fetchone()
        assert cid in {t["church_id"] for t in await r.churches_due_for_fetch(100, 30)}
        await r.insert_artifact(
            church_id=cid, url=f"https://rq{cid}.test", kind="homepage",
            http_status=200, fetch_error=None, robots_allowed=True,
            content_hash=f"rqh{cid}", r2_key=f"new-date/rqk{cid}",
            bytes_raw=100, bytes_text=50, crawl_run_id=None,
        )
        assert cid not in {t["church_id"] for t in await r.churches_due_for_fetch(100, 30)}
        async with r.con.cursor() as cur:
            await cur.execute(
                "SELECT id, extract_status, extracted_at, r2_key FROM raw_crawl_artifacts WHERE church_id=%s",
                (cid,),
            )
            assert await cur.fetchall() == [(artifact_id, status, extracted_at, f"rqk{cid}")]

    run_with_fixture(body)


def test_changed_content_still_creates_pending_extraction():
    async def body(r, ids):
        cid = ids[0]
        await r.insert_artifact(
            church_id=cid, url=f"https://rq{cid}.test", kind="homepage",
            http_status=200, fetch_error=None, robots_allowed=True,
            content_hash=f"changed-{cid}", r2_key=f"changed/rqk{cid}",
            bytes_raw=100, bytes_text=50, crawl_run_id=None,
        )
        targets = await r.pending_extract_targets(limit=10)
        target = next(t for t in targets if t["church_id"] == cid)
        assert target["r2_keys"] == [f"changed/rqk{cid}"]
        async with r.con.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM raw_crawl_artifacts WHERE church_id=%s", (cid,))
            assert await cur.fetchone() == (2,)

    run_with_fixture(body)
