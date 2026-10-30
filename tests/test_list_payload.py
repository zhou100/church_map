"""List responses stay cacheable and smaller without changing detail reads.

The search cards, language filter, and starting-point / fit ranking read a
few extracted_tags fields. Theology prose stays on the detail endpoint.
"""
from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import churches, stats as stats_mod
from backend.routers.churches import LIST_CACHE_CONTROL, _row_to_list_church

LONG_SUMMARY = (
    "A neighborhood congregation gathered around a shared table, "
    "with room for people who are new in town and still finding their way "
    "into a Sunday rhythm that is slower than the week around it, "
    "and a second sentence so the list payload has to cut the summary."
)
TAGS = {
    "service_languages": ["Spanish", "English"],
    "vibe_tags": ["intergenerational"],
    "worship_style": "blended",
    "programs": ["youth group"],
    "theological_stance": "moderate",
    "statement_of_faith": ["Salvation by grace through faith"],
    "theology_summary": "They teach a long theological paragraph. " * 8,
    "pull_quote": "We are glad you are here, neighbor.",
    "worship_style_detail": "Choir, organ, and a band on the last Sunday.",
}

ROW = {
    "id": 7,
    "name": "Grace Church",
    "review_count": 0,
    "website_summary": LONG_SUMMARY,
    "extracted_tags": TAGS,
}


class _Pool:
    def acquire(self):
        class Ctx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return None

        return Ctx()


class _Repo:
    def __init__(self, con):
        pass

    async def list_by_city_state(self, city, state, limit, offset, sort="default", **filters):
        return [dict(ROW)]

    async def get(self, church_id):
        return dict(ROW)

    async def fact_sources(self, church_id):
        return []


def _client(monkeypatch):
    monkeypatch.setattr(churches, "pool", _Pool())
    monkeypatch.setattr(churches, "ChurchRepository", _Repo)
    app = FastAPI()
    app.include_router(churches.router, prefix="/api")
    return TestClient(app)


def test_list_bounds_reject_before_the_database():
    app = FastAPI()
    app.include_router(churches.router, prefix="/api")
    client = TestClient(app)
    assert client.get("/api/churches?limit=0").status_code == 422
    assert client.get("/api/churches?limit=201").status_code == 422
    assert client.get("/api/churches?offset=-1").status_code == 422


def test_list_trims_payload_and_sets_public_cache(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/api/churches?city=Brooklyn&state=NY&limit=30")
    assert response.status_code == 200
    assert response.headers["cache-control"] == LIST_CACHE_CONTROL
    church = response.json()[0]
    assert church["website_summary"].endswith("…")
    assert len(church["website_summary"]) <= 201
    assert church["extracted_tags"]["service_languages"] == ["Spanish", "English"]
    assert church["extracted_tags"]["vibe_tags"] == ["intergenerational"]
    assert church["extracted_tags"]["worship_style"] == "blended"
    assert church["extracted_tags"]["programs"] == ["youth group"]
    assert church["extracted_tags"]["theological_stance"] == "moderate"
    assert church["extracted_tags"]["statement_of_faith"] == ["Salvation by grace through faith"]
    assert "theology_summary" not in church["extracted_tags"]
    assert "pull_quote" not in church["extracted_tags"]
    assert "worship_style_detail" not in church["extracted_tags"]


def test_detail_keeps_full_summary_and_is_not_list_cached(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/api/churches/7")
    assert response.status_code == 200
    assert response.headers.get("cache-control") != LIST_CACHE_CONTROL
    church = response.json()
    assert church["website_summary"] == LONG_SUMMARY
    assert church["extracted_tags"]["theology_summary"].startswith("They teach")
    assert church["extracted_tags"]["pull_quote"] == "We are glad you are here, neighbor."


def test_prose_only_extraction_still_counts_as_a_profile():
    church = _row_to_list_church({
        "id": 1,
        "name": "Quiet Chapel",
        "review_count": 0,
        "website_summary": None,
        "extracted_tags": {"theology_summary": "A short note about what they teach."},
    })
    assert church["website_summary"] is None
    assert church["extracted_tags"]["theology_summary"]


def test_stats_sets_shared_cache_without_a_browser_max_age():
    saved = dict(stats_mod._cache)
    stats_mod._cache["value"] = {"churches": {"total": 1}}
    stats_mod._cache["at"] = time.monotonic()
    try:
        app = FastAPI()
        app.include_router(stats_mod.router, prefix="/api")
        response = TestClient(app).get("/api/stats")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, s-maxage=300"
        assert response.json()["churches"]["total"] == 1
    finally:
        stats_mod._cache.clear()
        stats_mod._cache.update(saved)
