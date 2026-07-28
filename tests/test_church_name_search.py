"""Church-name search validation and SQL safety."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend.db.repository import ChurchRepository
from backend.routers.churches import list_churches, router


class _FakeCursor:
    def __init__(self):
        self.sql = ""
        self.params = ()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def execute(self, sql, params):
        self.sql = sql
        self.params = params

    async def fetchall(self):
        return []


class _FakeConnection:
    def __init__(self):
        self.last_cursor = None

    def cursor(self, **_kwargs):
        self.last_cursor = _FakeCursor()
        return self.last_cursor


def test_name_search_uses_bound_parameters():
    connection = _FakeConnection()
    query = "grace'; DROP TABLE churches;--"

    rows = asyncio.run(
        ChurchRepository(connection).search_by_name(query, limit=20, offset=5)
    )

    assert rows == []
    assert "DROP TABLE" not in connection.last_cursor.sql
    assert connection.last_cursor.params == (query, query, query, query, 20, 5)
    assert "STRPOS" in connection.last_cursor.sql
    assert "CASE" in connection.last_cursor.sql
    assert "website_summary IS NOT NULL" in connection.last_cursor.sql


def test_prerender_feed_uses_summary_gate_and_keyset_pagination():
    connection = _FakeConnection()

    rows = asyncio.run(
        ChurchRepository(connection).list_prerender_profiles(limit=500, after_id=123)
    )

    assert rows == []
    assert "BTRIM(c.website_summary) <> ''" in connection.last_cursor.sql
    assert "c.church_id > %s" in connection.last_cursor.sql
    assert "OFFSET" not in connection.last_cursor.sql
    assert connection.last_cursor.params == (123, 500)


def test_prerender_route_precedes_the_integer_detail_route():
    paths = [route.path for route in router.routes]
    assert paths.index("/churches/prerender") < paths.index("/churches/{church_id}")


def test_name_search_requires_two_characters():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(list_churches(name="G"))

    assert exc_info.value.status_code == 400
    assert "at least 2 characters" in exc_info.value.detail
