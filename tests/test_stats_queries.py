"""The two /api/stats queries whose logic lives in SQL, against a real Postgres.

`build_stats` is tested purely in test_stats.py, but it can only shape what the
queries hand it. Which runs count as progress, and which status strings fall in
which bucket, are decided by `FILTER (...)` and `CASE ... LIKE` — mocks agree
with whatever you assert, so these run against a database or not at all.

Same conventions as tests/scrapers_v2/test_requeue.py: asyncio.run rather than
an async plugin the suite doesn't have, and every test rolls back.

Both queries aggregate over the whole table, so nothing here asserts absolute
numbers. Run rows are stamped far in the future so MAX() provably returns the
seeded row; church counts are compared as deltas around the insert.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set; these assert on real SQL semantics",
)

# Far enough out that no real run can outrank it, and unambiguous in a dump.
FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)
SENTINEL_FLOOR = FUTURE - timedelta(days=1)


def _run(body):
    from psycopg import AsyncConnection

    from backend.db.repository import StatsRepository

    async def go():
        con = await AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            return await body(con, StatsRepository(con))
        finally:
            await con.rollback()
            await con.close()

    return asyncio.run(go())


async def _add_run(con, *, stage, status, rows_ok, finished_at=FUTURE):
    async with con.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO crawl_runs
                (stage, status, finished_at, batch_size,
                 rows_processed, rows_ok, rows_error, triggered_by)
            VALUES (%s, %s, %s, 75, %s, %s, %s, 'test')
            """,
            (stage, status, finished_at, rows_ok + 1, rows_ok, 1),
        )


async def _health_for(repo, stage):
    rows = (await repo.crawl_health())["last_success"]
    for r in rows:
        if r["stage"] == stage:
            return r
    return {"last_success": None, "last_progress": None}


def _is_sentinel(ts):
    """Did MAX() pick the row this test inserted, or something real?"""
    return ts is not None and ts >= SENTINEL_FLOOR


# --- which runs prove the stage is alive ------------------------------------


def test_clean_run_counts_as_both_success_and_progress():
    async def body(con, repo):
        await _add_run(con, stage="tag", status="ok", rows_ok=10)
        return await _health_for(repo, "tag")

    row = _run(body)
    assert _is_sentinel(row["last_success"])
    assert _is_sentinel(row["last_progress"])


def test_partial_run_that_got_rows_through_counts_as_progress_only():
    """The live bug, in one assertion. `status='ok'` requires zero failed rows,
    so every re-extraction batch with an error in it is 'partial'. Measured on
    the deployed endpoint 2026-07-27: extract's last 'ok' was 21h old and
    closing on its 24h budget while the stage ran on schedule and extracted
    churches. Staleness has to key on the second timestamp, not the first."""
    async def body(con, repo):
        await _add_run(con, stage="extract", status="partial", rows_ok=34)
        return await _health_for(repo, "extract")

    row = _run(body)
    assert not _is_sentinel(row["last_success"])   # still a flawed run
    assert _is_sentinel(row["last_progress"])      # but the stage is alive


def test_partial_run_with_nothing_through_is_not_progress():
    """The guard on the other side. A stage that runs on time and fails every
    single row is not working, and must not read as fresh — `rows_ok > 0` is
    what stops "grinding uselessly" from looking identical to "healthy"."""
    async def body(con, repo):
        await _add_run(con, stage="tag", status="partial", rows_ok=0)
        return await _health_for(repo, "tag")

    row = _run(body)
    assert not _is_sentinel(row["last_success"])
    assert not _is_sentinel(row["last_progress"])


def test_failed_run_counts_as_neither():
    async def body(con, repo):
        await _add_run(con, stage="fetch", status="error", rows_ok=0)
        return await _health_for(repo, "fetch")

    row = _run(body)
    assert not _is_sentinel(row["last_success"])
    assert not _is_sentinel(row["last_progress"])


def test_running_rows_do_not_count_before_they_finish():
    """A 'running' row has a NULL finished_at; an in-flight batch is not
    evidence of anything yet."""
    async def body(con, repo):
        await _add_run(con, stage="tag", status="running", rows_ok=5, finished_at=None)
        return await _health_for(repo, "tag")

    row = _run(body)
    assert not _is_sentinel(row["last_progress"])


# --- how failure statuses bucket --------------------------------------------

SEEDED_STATUSES = [
    "ok",
    "no-html:2/2",
    "no-text",
    "error:ExtractionError",
    "transient:TransientExtractionError",
    "transient:r2-unreadable:1/2",
    None,                      # attempted before extracted_status existed
    "something-else-entirely",
]
EXPECTED_DELTA = {
    "ok": 1,
    "no_html": 1,
    "no_text": 1,
    "error": 1,
    "transient": 2,
    "unknown": 1,
    "other": 1,
}


def test_status_strings_bucket_the_way_the_endpoint_claims():
    """Every status the extract stage actually writes, sorted. `no-html` must
    land apart from `no-text` (re-fetch vs. give up) and the r2-unreadable
    variant must land in `transient` (retries itself) rather than anywhere
    terminal — those are the distinctions the whole breakdown exists for."""
    async def body(con, repo):
        before = {r["status"]: r["count"] for r in await repo.extraction_status_breakdown()}
        async with con.cursor() as cur:
            for i, status in enumerate(SEEDED_STATUSES):
                await cur.execute(
                    """
                    INSERT INTO churches (name, website, extracted_at, extracted_status)
                    VALUES (%s, %s, NOW(), %s)
                    """,
                    (f"bucket test {i}", f"https://bucket-{i}.test", status),
                )
        after = {r["status"]: r["count"] for r in await repo.extraction_status_breakdown()}
        return before, after

    before, after = _run(body)
    delta = {k: after.get(k, 0) - before.get(k, 0) for k in set(before) | set(after)}
    assert {k: v for k, v in delta.items() if v} == EXPECTED_DELTA


def test_never_attempted_churches_are_not_counted_at_all():
    """The denominator is attempts. A church with no extracted_at was never
    tried, and folding it in would drown the failure rate in 128k rows."""
    async def body(con, repo):
        before = sum(r["count"] for r in await repo.extraction_status_breakdown())
        async with con.cursor() as cur:
            await cur.execute(
                "INSERT INTO churches (name, website) VALUES ('untried', 'https://untried.test')"
            )
        after = sum(r["count"] for r in await repo.extraction_status_breakdown())
        return before, after

    before, after = _run(body)
    assert after == before


def test_breakdown_totals_match_the_headline_extracted_count():
    """`church_counts().extracted` and this query must share a denominator, or
    the endpoint reports a failure rate against the wrong total."""
    async def body(con, repo):
        counts = await repo.church_counts()
        buckets = await repo.extraction_status_breakdown()
        return counts["extracted"], sum(r["count"] for r in buckets)

    extracted, bucketed = _run(body)
    assert extracted == bucketed
