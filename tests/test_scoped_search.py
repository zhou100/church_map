"""City-first progressive search: scope, distance order, For you ranking and
stable pages. Ordering and preference evidence are SQL, so the scope tests
run against a real Postgres; the request checks run without one."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.churches import router

pg = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set; scope SQL needs a real Postgres",
)
PARITY = json.loads((Path(__file__).parents[1] / "frontend/src/fitParityCases.json").read_text())


def test_bad_scope_requests_fail_before_database_access():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    for query, status in [
        ("city=A&state=ZZ&lat=1", 400),
        ("city=A&state=ZZ&lat=1&lon=2", 400),
        ("city=A&state=ZZ&radius_miles=5", 400),
        ("city=A&state=ZZ&sort=closest", 400),
        ("city=A&state=ZZ&sort=for_you&prefer_worship=loud", 400),
        ("city=A&state=ZZ&sort=for_you&prefer_language=" + "x" * 41, 400),
    ]:
        assert client.get("/churches?" + query).status_code == status, query


def run(body):
    from psycopg import AsyncConnection
    from backend.db.repository import ChurchRepository

    async def go():
        con = await AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            return await body(con, ChurchRepository(con))
        finally:
            await con.rollback()
            await con.close()
    return asyncio.run(go())


async def insert(con, name, city="Scopeville", lat=None, lon=-140.0, **cols):
    cols = {"name": name, "city": city, "state": "ZZ", "latitude": lat,
            "longitude": lon if lat is not None else None, **cols}
    if "extracted_tags" in cols:
        cols["extracted_tags"] = json.dumps(cols["extracted_tags"])
    async with con.cursor() as cur:
        await cur.execute(
            f"INSERT INTO churches ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
            " RETURNING church_id", list(cols.values()))
        return (await cur.fetchone())[0]


async def all_pages(repo, size, **kwargs):
    rows, offset = [], 0
    while True:
        page = await repo.list_scoped(limit=size, offset=offset, **kwargs)
        rows += page
        if len(page) < size:
            return rows
        offset += size


@pg
def test_city_scope_orders_by_distance_without_nearby_cities():
    async def body(con, repo):
        # Synthetic origin in open ocean keeps unrelated fixture rows away.
        for name, lat in [("far", 0.05), ("near", 0.01), ("mid", 0.02), ("tie-b", 0.03), ("tie-a", 0.03)]:
            await insert(con, f"scope {name}", lat=lat)
        await insert(con, "scope unmapped")
        await insert(con, "scope neighbour", city="Nextdoor", lat=0.001)
        kwargs = dict(city="Scopeville", state="ZZ", origin=(0.0, -140.0), sort="nearest")
        whole = await repo.list_scoped(limit=50, offset=0, **kwargs)
        assert [r["name"] for r in whole] == [
            "scope near", "scope mid", "scope tie-a", "scope tie-b", "scope far", "scope unmapped"]
        assert whole[-1]["distance_miles"] is None
        assert {r["total_count"] for r in whole} == {6}
        assert 0.6 < whole[0]["distance_miles"] < 0.7
        # Pages of two continue the same order with no repeat or gap.
        assert [r["id"] for r in await all_pages(repo, 2, **kwargs)] == [r["id"] for r in whole]
        # Without an origin a city is measured from its own approximate center
        # (median of mapped rows: lat 0.03), so every visitor gets one URL.
        centered = await repo.list_scoped(city="Scopeville", state="ZZ", sort="nearest", limit=3, offset=0)
        assert [r["name"] for r in centered] == ["scope tie-a", "scope tie-b", "scope mid"]
        assert centered[0]["distance_miles"] < 1e-6
        # The approximate centre is the median of mapped city rows only.
        assert await repo.city_center("Scopeville", "ZZ") == {"lat": 0.03, "lon": -140.0}
    run(body)


@pg
def test_radius_scope_is_the_only_one_that_crosses_city_lines():
    async def body(con, repo):
        await insert(con, "radius home", lat=0.01)
        await insert(con, "radius neighbour", city="Nextdoor", lat=0.02)
        await insert(con, "radius outside", lat=0.5)
        rows = await repo.list_scoped(near=(0.0, -140.0, 5), limit=50, offset=0)
        assert [r["name"] for r in rows] == ["radius home", "radius neighbour"]
        assert rows[0]["total_count"] == 2
    run(body)


@pg
def test_for_you_ranks_the_whole_scope_before_paging():
    async def body(con, repo):
        for i in range(24):
            await insert(con, f"fy filler {i:02}", lat=0.001 * (i + 1))
        await insert(con, "fy name guess", lat=0.0001, language="Vietnamese")
        await insert(con, "fy summary only", lat=0.2, website_summary="A parish.")
        match = await insert(con, "fy verified match", lat=0.3, service_languages="English; Vietnamese")
        await insert(con, "fy unmapped match", service_languages="Vietnamese",
                     extracted_tags={"worship_style": "liturgical"})
        kwargs = dict(city="Scopeville", state="ZZ", origin=(0.0, -140.0), sort="for_you",
                      prefs={"languages": ["vietnamese"], "worship": ["liturgical"], "kids": False})
        first = await repo.list_scoped(limit=20, offset=0, **kwargs)
        # Two answers beat one; evidence beats distance; completeness breaks ties.
        assert [r["name"] for r in first[:3]] == ["fy unmapped match", "fy verified match", "fy summary only"]
        assert first[1]["id"] == match
        # Unknown is not "no": nothing is filtered, and the name guess scores 0.
        assert first[0]["total_count"] == 28
        whole = await all_pages(repo, 20, **kwargs)
        assert len({r["id"] for r in whole}) == 28
        assert next(r for r in whole if r["name"] == "fy name guess")["fit_score"] == 0
    run(body)


@pg
def test_name_scope_for_you_keeps_the_name_match():
    async def body(con, repo):
        await insert(con, "Zq Grace Chapel", lat=0.01)
        await insert(con, "Zq Grace Kids", lat=0.02, kids_program="Nursery")
        await insert(con, "Unrelated", lat=0.0, kids_program="Nursery")
        rows = await repo.list_scoped(name="zq grace", sort="for_you", prefs={"kids": True},
                                      limit=50, offset=0)
        assert [r["name"] for r in rows] == ["Zq Grace Kids", "Zq Grace Chapel"]
    run(body)


@pg
@pytest.mark.parametrize("case", PARITY["cases"], ids=lambda case: case["name"])
def test_server_fit_counts_what_fitScore_counts(case):
    async def body(con, repo):
        cols = {k: case[k] for k in ("service_languages", "extracted_tags", "language",
                                      "cultural_background", "kids_program") if k in case}
        church = await insert(con, "parity case", city="Parityville", lat=0.0, **cols)
        for score in case.get("reviews", []):
            await con.execute("INSERT INTO reviews (church_id, rating, childrens_programs) VALUES (%s, 5, %s)",
                              (church, score))
        rows = await repo.list_scoped(city="Parityville", state="ZZ", sort="for_you",
                                      prefs=PARITY["prefs"], limit=5, offset=0)
        assert rows[0]["fit_score"] == case["score"]
    run(body)
