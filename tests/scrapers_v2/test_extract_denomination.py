"""write_extraction keeps the model's denomination apart from the directory's (real SQL).

Until migration 0009 it ran `denomination = COALESCE(<model>, denomination)`, so a
website the directory had wrong (church 96132, a Christian Reformed listing whose
website belongs to a Unitarian congregation) rewrote the directory field that D-1
scope and the visitor-facing label rely on, and the directory value was lost.
"""
from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set; this asserts on real SQL semantics",
)


def _run(body):
    from psycopg import AsyncConnection

    from backend.db.repository import CrawlRepository

    async def go():
        con = await AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            async with con.cursor() as cur:
                await cur.execute(
                    "INSERT INTO churches (name, denomination, source) "
                    "VALUES ('Denomination fixture', 'Christian Reformed', 'osm') RETURNING church_id")
                church_id = (await cur.fetchone())[0]
            return await body(con, CrawlRepository(con), church_id)
        finally:
            await con.rollback()
            await con.close()

    return asyncio.run(go())


async def _extract(repo, church_id, reading):
    await repo.write_extraction(
        church_id, website_summary="summary", extracted_tags={},
        extracted_denomination=reading, prompt_version="test", model="test",
        confidence={}, source_snippets={})


async def _row(con, church_id):
    async with con.cursor() as cur:
        await cur.execute("SELECT denomination, extracted_denomination FROM churches WHERE church_id = %s",
                          (church_id,))
        return await cur.fetchone()


def test_a_website_reading_never_rewrites_the_directory_denomination():
    async def body(con, repo, church_id):
        await _extract(repo, church_id, "Unitarian Universalist")
        first = await _row(con, church_id)
        # The latest reading replaces an earlier one, including a reading of nothing.
        await _extract(repo, church_id, None)
        second = await _row(con, church_id)
        return first, second

    first, second = _run(body)
    assert first == ("Christian Reformed", "Unitarian Universalist")
    assert second == ("Christian Reformed", None)
