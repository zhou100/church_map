"""City listing order: the default, and `sort=starting_point` for the landing page."""
from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi import HTTPException

from backend.db.repository import ChurchRepository
from backend.routers.churches import list_churches
from tests.test_church_name_search import _FakeConnection


def _city_sql(**kwargs):
    connection = _FakeConnection()
    asyncio.run(
        ChurchRepository(connection).list_by_city_state("Brooklyn", "NY", 100, 0, **kwargs)
    )
    return connection.last_cursor


def test_default_order_is_unchanged():
    cursor = _city_sql()
    assert "website_summary IS NOT NULL OR c.extracted_tags IS NOT NULL" in cursor.sql
    assert "jsonb_array_length" not in cursor.sql
    assert cursor.params == ("Brooklyn", "NY", 100, 0)


def test_starting_point_order_scores_before_the_limit():
    cursor = _city_sql(sort="starting_point")
    order_by = cursor.sql.split("ORDER BY", 1)[1]
    assert "COUNT(r.review_id) > 0 THEN 3" in order_by
    assert order_by.index("jsonb_array_length") < order_by.index("LIMIT")
    assert cursor.params == ("Brooklyn", "NY", 100, 0)


def test_unknown_sort_is_rejected():
    """A typo'd sort would silently fall back to some other order, which the
    landing page could not tell apart from "these are the best churches"."""
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(list_churches(city="Brooklyn", state="NY", sort="best"))

    assert exc_info.value.status_code == 400
    assert "starting_point" in exc_info.value.detail


pg = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set; ordering SQL needs a real Postgres",
)

FULL_TAGS = {
    "service_languages": ["English"],
    "worship_style": "liturgical",
    "programs": ["Sunday school"],
    "theological_stance": "traditional",
}


@pg
def test_starting_point_puts_the_richest_profile_first():
    """Default order is profile presence, then name, so a summary-only "a…"
    church beats a fully documented "z…" one. The landing order must not."""
    from psycopg import AsyncConnection

    async def go():
        con = await AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            async with con.cursor() as cur:
                for name, summary, times, tags in [
                    ("ord a summary only", "A neighborhood church.", None, None),
                    ("ord z full", "A neighborhood church.", "Sun 10am", FULL_TAGS),
                    ("ord aaa empty", None, None, None),
                ]:
                    await cur.execute(
                        """
                        INSERT INTO churches
                            (name, city, state, website_summary, service_times, extracted_tags)
                        VALUES (%s, 'Orderville', 'ZZ', %s, %s, %s::jsonb)
                        """,
                        (name, summary, times, json.dumps(tags) if tags else None),
                    )
            repo = ChurchRepository(con)
            default = await repo.list_by_city_state("Orderville", "ZZ", 50, 0)
            ranked = await repo.list_by_city_state(
                "Orderville", "ZZ", 50, 0, sort="starting_point"
            )
            return [r["name"] for r in default], [r["name"] for r in ranked]
        finally:
            await con.rollback()
            await con.close()

    default, ranked = asyncio.run(go())
    assert default == ["ord a summary only", "ord z full", "ord aaa empty"]
    assert ranked == ["ord z full", "ord a summary only", "ord aaa empty"]
