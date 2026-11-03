"""A timed-out church must stay due without undoing completed churches.

Real Postgres checks savepoint rollback, including ON CONFLICT freshness
updates; an in-memory fake cannot establish those semantics.
"""
import asyncio
import os

import pytest
from psycopg import AsyncConnection

from backend.db.repository import CrawlRepository
from backend.scrapers_v2 import fetch as fetch_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set; needs isolated Postgres",
)


@pytest.mark.parametrize("existing_homepage", [False, True])
def test_deadline_rolls_back_only_the_incomplete_church(monkeypatch, existing_homepage):
    async def main():
        con = await AsyncConnection.connect(os.environ["DATABASE_URL"], prepare_threshold=None)
        try:
            ids = []
            for name in ("finished", "interrupted", "not started"):
                cur = await con.execute(
                    "INSERT INTO churches (name, website) VALUES (%s, %s) RETURNING church_id",
                    (f"deadline {name}", f"https://deadline-{len(ids)}.test/"),
                )
                ids.append((await cur.fetchone())[0])

            class Repo(CrawlRepository):
                async def churches_due_for_fetch(self, limit, fresh_days):
                    targets = await super().churches_due_for_fetch(10_000, fresh_days)
                    return sorted((t for t in targets if t["church_id"] in ids),
                                  key=lambda t: t["church_id"])[:limit]

            repo = Repo(con)

            async def write_homepage(church_id, website):
                await repo.insert_artifact(
                    church_id=church_id, url=website, kind="homepage", http_status=200,
                    fetch_error=None, robots_allowed=True, content_hash="unchanged",
                    r2_key=f"test/{church_id}", bytes_raw=100, bytes_text=50, crawl_run_id=None,
                )

            original = None
            if existing_homepage:
                await write_homepage(ids[1], "https://deadline-1.test/")
                cur = await con.execute(
                    """UPDATE raw_crawl_artifacts
                          SET fetched_at = NOW() - INTERVAL '60 days', extract_status = 'ok'
                        WHERE church_id = %s RETURNING fetched_at, extract_status""", (ids[1],),
                )
                original = await cur.fetchone()

            deadlines = []
            real_timeout = asyncio.timeout

            def timeout(seconds):
                deadline = real_timeout(seconds)
                deadlines.append(deadline)
                return deadline

            interrupt = True

            async def fetch(client, repo, r2, church_id, website, crawl_run_id):
                await write_homepage(church_id, website)
                if church_id == ids[1] and interrupt:
                    # Expire only after the real homepage INSERT/UPDATE. This
                    # models a deadline hit on a subsequent page, without a
                    # wall-clock race between database speed and a short timer.
                    deadlines[-1].reschedule(asyncio.get_running_loop().time())
                    await asyncio.sleep(0)
                return 1

            monkeypatch.setattr(fetch_mod.asyncio, "timeout", timeout)
            monkeypatch.setattr(fetch_mod, "fetch_church", fetch)
            out = await fetch_mod.run_fetch_batch(
                repo, None, batch_size=3, fresh_days=30, crawl_run_id=None,
            )
            assert (out["rows_processed"], out["rows_ok"], out["rows_error"], out["deferred"]) == (1, 1, 0, 2)
            assert out["errors"] == []
            cur = await con.execute(
                "SELECT fetched_at, extract_status FROM raw_crawl_artifacts WHERE church_id = %s",
                (ids[1],),
            )
            assert await cur.fetchall() == ([original] if existing_homepage else [])
            due = await repo.churches_due_for_fetch(3, 30)
            assert [t["church_id"] for t in due] == ids[1:]

            # The same connection and deferred targets remain usable. The
            # completed church is fresh; retrying the rest finishes the batch.
            interrupt = False
            out = await fetch_mod.run_fetch_batch(
                repo, None, batch_size=3, fresh_days=30, crawl_run_id=None,
            )
            assert (out["rows_processed"], out["rows_ok"], out["deferred"]) == (2, 2, 0)
            assert await repo.churches_due_for_fetch(3, 30) == []
        finally:
            await con.rollback()
            await con.close()

    asyncio.run(main())
