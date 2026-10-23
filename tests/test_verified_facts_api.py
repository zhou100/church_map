"""Verified facts in the churches API (migration 0006), without a database.

Every public read hides out-of-scope rows (D-1); the new fields come back as
None/[] when a church has none; the detail endpoint carries fact_sources.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from backend.db.repository import VISIBLE, ChurchRepository
from backend.routers import churches as router_mod


class _FakeCursor:
    def __init__(self, rows):
        self.sql, self.params, self.rows = "", (), rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def execute(self, sql, params):
        self.sql, self.params = sql, params

    async def fetchall(self):
        return self.rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None


class _FakeConnection:
    def __init__(self, rows=()):
        self.rows, self.cursors = list(rows), []

    def cursor(self, **_kwargs):
        self.cursors.append(_FakeCursor(self.rows))
        return self.cursors[-1]


def _sql(call):
    con = _FakeConnection()
    asyncio.run(call(ChurchRepository(con)))
    return con.cursors[-1].sql


def test_every_public_read_hides_out_of_scope_churches():
    reads = {
        "zip": lambda r: r.list_by_zip("94110", 5, 0),
        "city": lambda r: r.list_by_city_state("San Mateo", "CA", 5, 0),
        "name": lambda r: r.search_by_name("grace", 5, 0),
        "detail": lambda r: r.get(1),
        "prerender": lambda r: r.list_prerender_profiles(5, 0),
        "similar": lambda r: r.similar(1),
    }
    for name, call in reads.items():
        assert VISIBLE in _sql(call), f"{name} does not apply the scope filter"


def test_visibility_keeps_legacy_and_in_scope_rows_only():
    assert "c.scope_status IS NULL" in VISIBLE
    assert "'in_scope', 'in_scope_labeled'" in VISIBLE


BASE = {"id": 7, "name": "Grace Church", "review_count": 0}


def test_new_fields_default_to_empty():
    church = router_mod._row_to_church(dict(BASE))
    assert (church["kids_program"], church["facebook_url"], church["service_languages"],
            church["display_tradition"], church["verified_at"]) == (None, None, [], None, None)


def test_new_fields_are_mapped():
    when = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
    church = router_mod._row_to_church({**BASE, "kids_program": "Sunday school 9:30am",
                                        "facebook_url": "https://www.facebook.com/grace",
                                        "service_languages": "Mandarin; English;",
                                        "display_tradition": "Latter-day Saints", "verified_at": when})
    assert church["service_languages"] == ["Mandarin", "English"]
    assert church["verified_at"] == "2026-10-21T18:00:00+00:00"
    assert church["kids_program"] == "Sunday school 9:30am"


def test_detail_carries_fact_sources(monkeypatch):
    when = datetime(2026, 10, 20, tzinfo=timezone.utc)

    class Repo:
        def __init__(self, con):
            pass

        async def get(self, church_id):
            return dict(BASE)

        async def fact_sources(self, church_id):
            return [{"field": "service_times", "source_url": "https://grace.example.org/visit",
                     "source_type": "own_site", "checked_at": when}]

    class Pool:
        def acquire(self):
            class Ctx:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, *exc):
                    return None
            return Ctx()

    monkeypatch.setattr(router_mod, "ChurchRepository", Repo)
    monkeypatch.setattr(router_mod, "pool", Pool())
    church = asyncio.run(router_mod.get_church(7))
    assert church["fact_sources"] == {"service_times": {"source_url": "https://grace.example.org/visit",
                                                        "source_type": "own_site",
                                                        "checked_at": "2026-10-20T00:00:00+00:00"}}
