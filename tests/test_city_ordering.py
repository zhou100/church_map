"""City listing order: the default, `sort=starting_point` for the landing page and
`sort=nearest` for Search."""
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


def test_starting_point_ranks_score_then_distance_before_the_limit():
    cursor = _city_sql(sort="starting_point")
    order_by = cursor.sql.split("ORDER BY", 1)[1]
    assert "COUNT(r.review_id) > 0 THEN 3" in order_by
    assert order_by.index("jsonb_array_length") < order_by.index("percentile_disc")
    assert order_by.index("percentile_disc") < order_by.index("LIMIT")
    # the two city medians bind the city again, after the WHERE params
    assert cursor.params == ("Brooklyn", "NY", "Brooklyn", "NY", "Brooklyn", "NY", 100, 0)


def test_nearest_orders_by_distance_from_the_city_middle_before_the_limit():
    cursor = _city_sql(sort="nearest")
    order_by = cursor.sql.rsplit("ORDER BY", 1)[1]
    assert order_by.index("distance_miles ASC NULLS LAST") < order_by.index("profile_score"), \
        "distance first; profile richness only breaks exact ties"
    assert order_by.index("NULLS LAST") < order_by.index("LIMIT")
    # Great-circle distance from the city's median coordinates: latitude twice
    # (offset and scale), longitude once, each binding the city again.
    assert cursor.sql.count("percentile_cont") == 3
    assert tuple(cursor.params) == (*("Brooklyn", "NY") * 4, 100, 0)


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


SUMMARY = "A neighborhood church."


def _ranked_names(seed, limit, sort="starting_point"):
    """Insert `seed` rows into Orderville, ZZ and return the names in default
    and `sort` order, each cut at `limit`. Rolled back afterwards."""
    from psycopg import AsyncConnection

    async def go():
        con = await AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            async with con.cursor() as cur:
                for name, summary, times, tags, lat, lon in seed:
                    await cur.execute(
                        """
                        INSERT INTO churches (name, city, state, website_summary,
                                              service_times, extracted_tags, latitude, longitude)
                        VALUES (%s, 'Orderville', 'ZZ', %s, %s, %s::jsonb, %s, %s)
                        """,
                        (name, summary, times, json.dumps(tags) if tags else None, lat, lon),
                    )
            repo = ChurchRepository(con)
            default = await repo.list_by_city_state("Orderville", "ZZ", limit, 0)
            ranked = await repo.list_by_city_state(
                "Orderville", "ZZ", limit, 0, sort=sort
            )
            return [r["name"] for r in default], [r["name"] for r in ranked]
        finally:
            await con.rollback()
            await con.close()

    return asyncio.run(go())


@pg
def test_starting_point_puts_the_richest_profile_first():
    """Default order is profile presence, then name, so a summary-only "a…"
    church beats a fully documented "z…" one. The landing order must not."""
    default, ranked = _ranked_names([
        ("ord a summary only", SUMMARY, None, None, None, None),
        ("ord z full", SUMMARY, "Sun 10am", FULL_TAGS, None, None),
        ("ord aaa empty", None, None, None, None, None),
    ], limit=50)
    assert default == ["ord a summary only", "ord z full", "ord aaa empty"]
    assert ranked == ["ord z full", "ord a summary only", "ord aaa empty"]


@pg
def test_starting_point_breaks_ties_toward_the_middle_before_the_limit():
    """Equal scores: the church at the city's median coordinates must survive
    LIMIT even though every other one sorts ahead of it by name. An unmapped
    church ties last."""
    seed = [
        ("tie a west", SUMMARY, None, None, 40.50, -74.20),
        ("tie b east", SUMMARY, None, None, 40.90, -73.70),
        ("tie c unmapped", SUMMARY, None, None, None, None),
        ("tie z middle", SUMMARY, None, None, 40.70, -73.95),
    ]
    assert _ranked_names(seed, limit=1) == (["tie a west"], ["tie z middle"])
    _, ranked = _ranked_names(seed, limit=4)
    assert ranked[-1] == "tie c unmapped"


@pg
def test_nearest_puts_the_closest_church_to_the_middle_first_before_the_limit():
    """Profile richness doesn't matter here: a bare church at the middle beats a
    fully documented one at the edge, page one ends nearest-first, and an
    unmapped church comes last."""
    seed = [
        ("near a full edge", SUMMARY, "Sun 10am", FULL_TAGS, 40.50, -74.20),
        ("near b east", None, None, None, 40.70, -73.80),
        ("near c unmapped", SUMMARY, None, None, None, None),
        ("near z middle", None, None, None, 40.70, -73.95),
        ("near y close", None, None, None, 40.72, -73.95),
    ]
    _, first = _ranked_names(seed, limit=2, sort="nearest")
    assert first == ["near z middle", "near y close"]
    _, ranked = _ranked_names(seed, limit=5, sort="nearest")
    assert ranked[-1] == "near c unmapped"
