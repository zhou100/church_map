"""Filtering search on crawled website data (`churches.extracted_tags`).

The clause builder is pure and tested directly; the SQL it produces is
exercised against a real Postgres below, because JSONB predicates are
exactly the kind of thing that looks right and isn't.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from backend.db.repository import extracted_filters

# --- clause builder (pure) -------------------------------------------------


def test_no_filters_produces_no_sql():
    where, params = extracted_filters()
    assert where == ""
    assert params == []


def test_empty_strings_are_not_filters():
    """The router passes "" for absent query params; those must not become
    a predicate that matches nothing."""
    where, params = extracted_filters(language="", worship_style="", stance="")
    assert where == ""
    assert params == []


def test_each_filter_contributes_one_param():
    where, params = extracted_filters(
        language="Spanish", worship_style="liturgical", stance="traditional"
    )
    assert params == ["Spanish", "liturgical", "traditional"]
    assert where.count("AND (") == 3


def test_values_never_reach_the_clause_text():
    """Clause text is literals only — values ride in %s."""
    where, params = extracted_filters(language="'; DROP TABLE churches;--")
    assert "DROP TABLE" not in where
    assert params == ["'; DROP TABLE churches;--"]
    assert where.count("%s") == 1


def test_language_guards_against_a_non_array():
    """jsonb_array_elements_text raises on a scalar, which would 500 the
    endpoint for one malformed row."""
    where, _ = extracted_filters(language="English")
    assert "jsonb_typeof" in where


# --- against a real database -----------------------------------------------

pg = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set; filter SQL needs a real Postgres",
)

TAGS_ES = {
    "service_languages": ["English", "Spanish"],
    "worship_style": "liturgical",
    "theological_stance": "traditional",
}
TAGS_EN = {
    "service_languages": ["English"],
    "worship_style": "contemporary",
    "theological_stance": "progressive",
}
TAGS_MALFORMED = {"service_languages": "English"}   # a string, not an array


def run_with_churches(body):
    """Seed four churches in one city, run `body(repo, names)`, roll back."""
    from psycopg import AsyncConnection

    from backend.db.repository import ChurchRepository

    async def go():
        con = await AsyncConnection.connect(os.environ["DATABASE_URL"])
        try:
            async with con.cursor() as cur:
                for name, tags in [
                    ("flt bilingual", TAGS_ES),
                    ("flt english", TAGS_EN),
                    ("flt malformed", TAGS_MALFORMED),
                    ("flt unextracted", None),
                ]:
                    await cur.execute(
                        """
                        INSERT INTO churches (name, city, state, extracted_tags)
                        VALUES (%s, 'Filterville', 'ZZ', %s::jsonb)
                        """,
                        (name, json.dumps(tags) if tags is not None else None),
                    )
            return await body(ChurchRepository(con))
        finally:
            await con.rollback()
            await con.close()

    return asyncio.run(go())


async def _names(repo, **filters):
    rows = await repo.list_by_city_state("Filterville", "ZZ", 50, 0, **filters)
    return {r["name"] for r in rows}


@pg
def test_unfiltered_returns_every_seeded_church():
    async def body(repo):
        assert await _names(repo) == {
            "flt bilingual", "flt english", "flt malformed", "flt unextracted",
        }

    run_with_churches(body)


@pg
def test_language_filter_matches_inside_the_array():
    async def body(repo):
        assert await _names(repo, language="Spanish") == {"flt bilingual"}
        assert await _names(repo, language="English") == {"flt bilingual", "flt english"}

    run_with_churches(body)


@pg
def test_language_filter_is_case_insensitive():
    async def body(repo):
        assert await _names(repo, language="spanish") == {"flt bilingual"}
        assert await _names(repo, language="SPANISH") == {"flt bilingual"}

    run_with_churches(body)


@pg
def test_a_malformed_row_does_not_blow_up_the_query():
    """One church with service_languages as a string must not 500 the search
    for everybody else — it just never matches."""
    async def body(repo):
        assert "flt malformed" not in await _names(repo, language="English")

    run_with_churches(body)


@pg
def test_unextracted_churches_never_match_a_filter():
    """Honest exclusion: we don't know a church's language until something
    read its website. This is why filter usefulness tracks backfill progress."""
    async def body(repo):
        for f in ({"language": "English"}, {"worship_style": "liturgical"},
                  {"stance": "traditional"}):
            assert "flt unextracted" not in await _names(repo, **f)

    run_with_churches(body)


@pg
def test_worship_style_and_stance_filter_on_scalars():
    async def body(repo):
        assert await _names(repo, worship_style="liturgical") == {"flt bilingual"}
        assert await _names(repo, stance="progressive") == {"flt english"}

    run_with_churches(body)


@pg
def test_filters_combine_as_and_not_or():
    async def body(repo):
        both = await _names(repo, language="English", worship_style="contemporary")
        assert both == {"flt english"}
        # contradictory pair matches nothing rather than everything
        assert await _names(repo, language="Spanish", stance="progressive") == set()

    run_with_churches(body)


@pg
def test_zip_search_filters_too():
    async def body(repo):
        rows = await repo.list_by_zip("00000", 50, 0, language="Spanish")
        assert isinstance(rows, list)   # SQL is valid with filters appended

    run_with_churches(body)
