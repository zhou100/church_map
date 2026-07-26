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
