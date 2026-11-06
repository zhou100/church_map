"""Programs stage against a real Postgres: which churches are due, what an
extraction writes, and what the API returns. Work selection and replacement
are SQL, which mocks agree with and databases don't.

Each test seeds its own rows through the fetch stage's insert_artifact (so an
unchanged re-fetch takes the real ON CONFLICT path) and rolls back.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set; programs SQL needs a real Postgres",
)

WHEN = datetime(2026, 11, 3, 18, tzinfo=timezone.utc)


def run(body):
    from psycopg import AsyncConnection

    from backend.db.repository import ChurchRepository, CrawlRepository, ProgramRepository

    async def go():
        con = await AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            return await body(con, CrawlRepository(con), ProgramRepository(con), ChurchRepository(con))
        finally:
            await con.rollback()
            await con.close()
    return asyncio.run(go())


async def church(con, name, **cols):
    cols = {"name": name, "city": "Programville", "state": "ZZ", "website": f"https://{name}.test", **cols}
    async with con.cursor() as cur:
        await cur.execute(
            f"INSERT INTO churches ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
            " RETURNING church_id", list(cols.values()))
        return (await cur.fetchone())[0]


async def page(crawl, cid, kind, chash, *, path=None, status=200):
    return await crawl.insert_artifact(
        church_id=cid, url=f"https://c{cid}.test/{path if path is not None else kind}", kind=kind,
        http_status=status, fetch_error=None if status == 200 else "upstream",
        robots_allowed=True, content_hash=chash if status == 200 else None,
        r2_key=f"raw_html/{cid}/2026-11-03/{chash}.html" if status == 200 else None,
        bytes_raw=10, bytes_text=10, crawl_run_id=None)


async def due(programs, ids):
    return {r["church_id"]: r for r in await programs.due_for_program_extraction(limit=10_000)
            if r["church_id"] in ids}


async def done(programs, target, rows=(), status="ok"):
    await programs.record_program_extraction(
        target["church_id"], target["artifact_ids"], status=status,
        programs=None if status == "error" else list(rows), pages_read=len(target["artifact_ids"]),
        dropped={}, extractor_version="test.v1", model="test/model")


def program(cid, artifact_id, *, bands=(), ptype=None, name="Nursery"):
    return {"program_type": ptype, "age_bands": list(bands), "name_stated": name, "ages_stated": None,
            "schedule_stated": None, "campus_stated": None,
            "excerpt": f"{name} is open during both services.", "excerpt_start": 0, "excerpt_end": 30,
            "source_url": f"https://c{cid}.test/kids", "artifact_id": artifact_id, "r2_key": "k",
            "content_hash": "h", "raw_sha256": "r" * 64, "text_sha256": "t" * 64, "page_fetched_at": WHEN}


def test_due_set_follows_page_changes_not_refetches():
    async def body(con, crawl, programs, _):
        cid = await church(con, "prog-a")
        home = await page(crawl, cid, "homepage", "home1")
        kids = await page(crawl, cid, "kids", "kids1")
        about = await page(crawl, cid, "about", "about1")      # website_v3 only, not read
        await page(crawl, cid, "sermons", "sermons1")          # visit page, not about programs
        t = (await due(programs, {cid}))[cid]
        assert t["artifact_ids"] == [kids, home] and t["kinds"] == ["kids", "homepage"]
        assert about not in t["artifact_ids"]
        assert (t["name"], t["city"]) == ("prog-a", "Programville")
        await done(programs, t)
        assert await due(programs, {cid}) == {}

        # Unchanged re-fetch: same artifact ids, fetched_at refreshed. No new work.
        assert await page(crawl, cid, "homepage", "home1") == home
        assert await page(crawl, cid, "kids", "kids1") == kids
        assert await due(programs, {cid}) == {}

        # A failed re-fetch of the kids page keeps its archived version. No new work.
        await page(crawl, cid, "kids", None, status=500)
        assert await due(programs, {cid}) == {}

        # Changed kids page: a new artifact replaces the old one in the input.
        kids2 = await page(crawl, cid, "kids", "kids2")
        t = (await due(programs, {cid}))[cid]
        assert t["artifact_ids"] == [kids2, home]

        # The website_v3 queue is untouched by any of this.
        async with con.cursor() as cur:
            await cur.execute("SELECT DISTINCT extract_status FROM raw_crawl_artifacts WHERE church_id = %s", (cid,))
            assert [r[0] for r in await cur.fetchall()] == ["pending"]
    run(body)


def test_only_the_latest_crawl_counts_and_hidden_churches_are_never_due():
    async def body(con, crawl, programs, _):
        cid = await church(con, "prog-b")
        old_kids = await page(crawl, cid, "kids", "oldkids", path="old-kids")
        async with con.cursor() as cur:
            await cur.execute("UPDATE raw_crawl_artifacts SET fetched_at = NOW() - INTERVAL '40 days'"
                              " WHERE id = %s", (old_kids,))
        home = await page(crawl, cid, "homepage", "home1")
        hidden = await church(con, "prog-hidden", scope_status="out_of_scope")
        await page(crawl, hidden, "homepage", "h1")
        await page(crawl, hidden, "kids", "k1")
        nohome = await church(con, "prog-nohome")
        await page(crawl, nohome, "kids", "k1")  # no archived homepage: no crawl to anchor on
        got = await due(programs, {cid, hidden, nohome})
        assert set(got) == {cid}
        assert got[cid]["artifact_ids"] == [home]  # the unlinked old kids page dropped out
    run(body)


def test_extraction_replaces_programs_and_a_bad_answer_keeps_them():
    async def body(con, crawl, programs, churches):
        cid = await church(con, "prog-c")
        await page(crawl, cid, "homepage", "home1")
        kids = await page(crawl, cid, "kids", "kids1")
        t = (await due(programs, {cid}))[cid]
        await done(programs, t, [program(cid, kids, bands=["preschool"], ptype="during_service"),
                                 program(cid, kids, bands=["young_adult"], ptype="other", name="College group")])
        rows = await churches.programs(cid)
        assert [r["name_stated"] for r in rows] == ["Nursery", "College group"]

        # Pages changed and the answer was junk: what was shown stays.
        await page(crawl, cid, "kids", "kids2")
        t = (await due(programs, {cid}))[cid]
        await done(programs, t, status="error")
        assert len(await churches.programs(cid)) == 2
        assert await due(programs, {cid}) == {}

        # Pages changed again and no longer mention programs: they are cleared.
        await page(crawl, cid, "kids", "kids3")
        t = (await due(programs, {cid}))[cid]
        await done(programs, t, status="no_program_text")
        assert await churches.programs(cid) == []
        async with con.cursor() as cur:
            await cur.execute("SELECT status, programs_kept, input_artifact_ids FROM church_program_extractions"
                              " WHERE church_id = %s", (cid,))
            status, kept, inputs = await cur.fetchone()
        assert (status, kept) == ("no_program_text", 0) and inputs == sorted(t["artifact_ids"])
    run(body)


def test_schema_rejects_unknown_bands_and_types():
    import psycopg

    async def body(con, crawl, programs, _):
        cid = await church(con, "prog-d")
        for bad in [dict(bands=["teens"]), dict(ptype="sunday")]:
            async with con.transaction():
                with pytest.raises(psycopg.errors.CheckViolation):
                    async with con.transaction():
                        await programs.record_program_extraction(
                            cid, [], status="ok", programs=[program(cid, None, **bad)], pages_read=0,
                            dropped={}, extractor_version="t", model=None)
    run(body)


def test_list_and_detail_carry_programs():
    from backend.db.repository import _DIM_SELECT
    from backend.routers import churches as router_mod

    async def body(con, crawl, programs, churches):
        cid = await church(con, "prog-e")
        await page(crawl, cid, "homepage", "home1")
        kids = await page(crawl, cid, "kids", "kids1")
        t = (await due(programs, {cid}))[cid]
        await done(programs, t, [program(cid, kids, bands=["preschool"], ptype="during_service")])
        listed = await churches.list_scoped(city="Programville", state="ZZ", sort="nearest", limit=50, offset=0)
        row = next(r for r in listed if r["id"] == cid)
        assert row["kids_programs"] == [{"program_type": "during_service", "age_bands": ["preschool"],
                                         "name_stated": "Nursery"}]
        detail = await churches.programs(cid)
        return row, detail

    row, detail = run(body)
    listed = router_mod._row_to_list_church({**row, "review_count": 0})
    assert listed["kids_programs"][0]["age_bands"] == ["preschool"]
    shown = router_mod._program(detail[0])
    assert datetime.fromisoformat(shown["checked_at"]) == WHEN
    assert shown["evidence_class"] == "website_claim"
    assert shown["source_url"].endswith("/kids") and shown["excerpt"].startswith("Nursery")
    assert "kids_programs" in _DIM_SELECT
