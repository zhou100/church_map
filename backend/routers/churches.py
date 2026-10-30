"""
Churches router. All SQL goes through ChurchRepository against the async
Postgres pool. The /enrich endpoint stays public because the frontend calls
it on every detail page load, but the enrichment work itself runs on a
sync psycopg connection (see backend.enrichment) wrapped in
asyncio.to_thread to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, HTTPException, Query, Response
from psycopg.rows import dict_row

from backend import enrichment
from backend.db import pool
from backend.db.repository import CITY_ORDERINGS, ChurchRepository, _normalize_extracted_tags
from backend.scrapers_v2.prompts.website_v3 import THEOLOGICAL_STANCES, WORSHIP_STYLES
from backend.utils import compute_tags

router = APIRouter()


def _row_to_church(row: dict, *, include_dims: bool = False) -> dict:
    dims = {
        "worship_energy": row.get("avg_worship_energy"),
        "community_warmth": row.get("avg_community_warmth"),
        "sermon_depth": row.get("avg_sermon_depth"),
        "childrens_programs": row.get("avg_childrens_programs"),
        "theological_openness": row.get("avg_theological_openness"),
        "facilities": row.get("avg_facilities"),
    }
    church = {
        "id": row["id"],
        "name": row["name"],
        "address": row.get("address"),
        "city": row.get("city"),
        "state": row.get("state"),
        "denomination": row.get("denomination"),
        "service_times": row.get("service_times"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "avg_rating": row.get("avg_rating"),
        "review_count": row.get("review_count") or 0,
        "website": row.get("website") or None,
        "phone": row.get("phone") or None,
        "language": row.get("language") or None,
        "cultural_background": row.get("cultural_background") or None,
        "tags": compute_tags(dims, row.get("review_count") or 0),
        "website_summary": row.get("website_summary") or None,
        "extracted_tags": _normalize_extracted_tags(row.get("extracted_tags")),
        # Verified facts (scripts/publish_verified.py): stated by the church's own
        # site, denomination or Facebook Page, and re-checked on that page.
        "kids_program": row.get("kids_program") or None,
        "facebook_url": row.get("facebook_url") or None,
        "service_languages": _split_languages(row.get("service_languages")),
        "display_tradition": row.get("display_tradition") or None,
        "verified_at": _iso(row.get("verified_at")),
    }
    if include_dims:
        church["dimensions"] = {
            k: (round(v, 2) if v is not None else None) for k, v in dims.items()
        }
    return church


def _split_languages(value: str | None) -> list[str]:
    return [lang.strip() for lang in (value or "").split(";") if lang.strip()]


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


# Fields the search cards, language filter, and "for you" / starting-point
# ranking actually read. Long prose (theology, pull quotes, worship detail)
# stays on the detail endpoint. A church whose only extracted content is that
# prose still returns one short field so "website profile" does not flip off.
_LIST_SUMMARY_LIMIT = 200
_LIST_TAG_KEYS = (
    "service_languages",
    "vibe_tags",
    "worship_style",
    "programs",
    "theological_stance",
    "statement_of_faith",
)
# Browsers revalidate every time, so a visitor who just left a review sees it on
# the next list. Only Vercel's CDN keeps a copy, briefly
# (Vercel-CDN-Cache-Control is read by Vercel and not passed on to browsers).
LIST_CACHE_CONTROL = "public, max-age=0, must-revalidate"
LIST_CDN_CACHE_CONTROL = "max-age=60, stale-while-revalidate=300"


def _tag_has_content(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    if isinstance(value, dict):
        return False
    return value not in (None, False)


def _truncate_text(value: str | None, limit: int = _LIST_SUMMARY_LIMIT) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    space = cut.rfind(" ")
    if space >= limit // 2:
        trimmed = cut[:space].rstrip(" ,;:")
        cut = trimmed or cut
    return f"{cut}…"


def _list_extracted_tags(tags):
    normalized = _normalize_extracted_tags(tags)
    if not isinstance(normalized, dict):
        return normalized
    kept = {
        key: normalized[key]
        for key in _LIST_TAG_KEYS
        if _tag_has_content(normalized.get(key))
    }
    if kept:
        return kept
    for key, value in normalized.items():
        if not _tag_has_content(value):
            continue
        if isinstance(value, str):
            short = _truncate_text(value, 80)
            return {key: short} if short else None
        if isinstance(value, list):
            return {key: value}
        if not isinstance(value, dict):
            return {key: value}
    return None


def _row_to_list_church(row: dict) -> dict:
    church = _row_to_church(row)
    church["website_summary"] = _truncate_text(church.get("website_summary"))
    tags = _list_extracted_tags(church.get("extracted_tags"))
    # Cards and ranking only check that a statement of faith exists; the
    # bullets themselves are on the detail endpoint.
    if isinstance(tags, dict) and "statement_of_faith" in tags:
        tags["statement_of_faith"] = True
    church["extracted_tags"] = tags
    return church


def _fact_sources(rows: list[dict]) -> dict:
    """field -> {source_url, source_type, checked_at}, for "Checked <date>" links."""
    return {r["field"]: {"source_url": r["source_url"], "source_type": r["source_type"],
                         "checked_at": _iso(r["checked_at"])} for r in rows}


def _row_to_prerender_church(row: dict) -> dict:
    """Public fields needed to build a useful static church profile."""
    return {
        "id": row["id"],
        "name": row["name"],
        "address": row.get("address"),
        "city": row.get("city"),
        "state": row.get("state"),
        "denomination": row.get("denomination"),
        "website": row.get("website") or None,
        "phone": row.get("phone") or None,
        "website_summary": row.get("website_summary") or None,
        "extracted_tags": _normalize_extracted_tags(row.get("extracted_tags")),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
    }


@router.get("/churches")
async def list_churches(
    name: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
    language: str = "",
    worship_style: str = "",
    stance: str = "",
    sort: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    response: Response = None,
):
    """Search churches by name or list them by location.

    `language`, `worship_style` and `stance` filter on `extracted_tags` —
    what the crawler read off each church's own site. A church with no
    extraction cannot match any of them, so coverage bounds how useful they
    are; see `extracted_filters` in the repository layer.

    `worship_style` and `stance` are validated against the extraction
    schema. Silently returning zero results for a typo'd bucket would be
    indistinguishable from "no churches like that near you", which is a much
    worse answer than saying the filter was wrong.

    `sort` orders a city listing (`default` or `starting_point`; see
    `CITY_ORDERINGS`). Name search keeps its relevance order and ZIP search
    its default order, so `sort` only applies to city/state.
    """
    name_query = name.strip()
    if name_query and len(name_query) < 2:
        raise HTTPException(
            status_code=400,
            detail="church name search must be at least 2 characters",
        )

    if worship_style and worship_style.lower() not in WORSHIP_STYLES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown worship_style; expected one of {sorted(WORSHIP_STYLES)}",
        )
    if stance and stance.lower() not in THEOLOGICAL_STANCES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown stance; expected one of {sorted(THEOLOGICAL_STANCES)}",
        )

    sort_key = sort.lower() or "default"
    if sort_key not in CITY_ORDERINGS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown sort; expected one of {sorted(CITY_ORDERINGS)}",
        )

    filters = {"language": language, "worship_style": worship_style, "stance": stance}
    async with pool.acquire() as con:
        repo = ChurchRepository(con)
        if name_query:
            rows = await repo.search_by_name(name_query, limit, offset, **filters)
        elif zip_code:
            rows = await repo.list_by_zip(zip_code, limit, offset, **filters)
        else:
            rows = await repo.list_by_city_state(
                city, state, limit, offset, sort=sort_key, **filters
            )
    if response is not None:
        response.headers["Cache-Control"] = LIST_CACHE_CONTROL
        response.headers["Vercel-CDN-Cache-Control"] = LIST_CDN_CACHE_CONTROL
    return [_row_to_list_church(r) for r in rows]


@router.get("/churches/prerender")
async def list_prerender_profiles(
    limit: int = Query(default=500, ge=1, le=500),
    after_id: int = Query(default=0, ge=0),
):
    """Page through churches that are substantial enough to publish.

    This is a build-time feed, not another search endpoint. It deliberately
    excludes churches without a website summary so static generation does not
    turn unknown data into thousands of thin indexable pages.
    """
    async with pool.acquire() as con:
        rows = await ChurchRepository(con).list_prerender_profiles(limit, after_id)
    return [_row_to_prerender_church(row) for row in rows]


@router.get("/churches/{church_id}")
async def get_church(church_id: int):
    async with pool.acquire() as con:
        repo = ChurchRepository(con)
        row = await repo.get(church_id)
        sources = await repo.fact_sources(church_id) if row else []
    if not row:
        raise HTTPException(status_code=404, detail="Church not found")
    church = _row_to_church(row, include_dims=True)
    church["fact_sources"] = _fact_sources(sources)
    return church


@router.get("/churches/{church_id}/similar")
async def get_similar_churches(church_id: int):
    async with pool.acquire() as con:
        repo = ChurchRepository(con)
        target = await repo.get(church_id)
        if not target:
            raise HTTPException(status_code=404, detail="Church not found")
        rows = await repo.similar(church_id, k=3)
    return [_row_to_church(r) for r in rows]


def _enrich_sync(church_id: int) -> dict | None:
    """
    Sync wrapper around backend.enrichment.enrich. Opens its own short-lived
    psycopg connection because enrichment.enrich is sync (it calls requests
    against Google Places) and pool acquisition for blocking work would
    starve the async pool. Cap is 3000 calls/month; this path is rare.
    """
    import psycopg

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return None
    with psycopg.connect(dsn) as con:
        return enrichment.enrich(church_id, con)


@router.post("/churches/{church_id}/enrich")
async def enrich_church(church_id: int):
    """Trigger Google Places enrichment for a church. Idempotent and cap-safe."""
    result = await asyncio.to_thread(_enrich_sync, church_id)
    if result is not None:
        return result

    # Cache hit with no fresh data, cap reached, or no API key. Return what
    # is already stored so the frontend can render existing photos/hours
    # without an extra round-trip.
    async with pool.acquire() as con:
        async with con.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT google_photos, google_hours FROM churches WHERE church_id = %s",
                (church_id,),
            )
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Church not found")

    def _coerce(v):
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return []

    return {
        "photos": _coerce(row["google_photos"]),
        "hours": _coerce(row["google_hours"]),
    }
