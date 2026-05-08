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

from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from backend import enrichment
from backend.db import pool
from backend.db.repository import ChurchRepository, _normalize_extracted_tags
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
    }
    if include_dims:
        church["dimensions"] = {
            k: (round(v, 2) if v is not None else None) for k, v in dims.items()
        }
    return church


@router.get("/churches")
async def list_churches(
    city: str = "",
    state: str = "",
    zip_code: str = "",
    limit: int = 50,
    offset: int = 0,
):
    async with pool.acquire() as con:
        repo = ChurchRepository(con)
        if zip_code:
            rows = await repo.list_by_zip(zip_code, limit, offset)
        else:
            rows = await repo.list_by_city_state(city, state, limit, offset)
    return [_row_to_church(r) for r in rows]


@router.get("/churches/{church_id}")
async def get_church(church_id: int):
    async with pool.acquire() as con:
        repo = ChurchRepository(con)
        row = await repo.get(church_id)
    if not row:
        raise HTTPException(status_code=404, detail="Church not found")
    return _row_to_church(row, include_dims=True)


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
