import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from holyhub.database import Database
from backend.deps import get_db
from backend.utils import compute_tags
from backend import enrichment

router = APIRouter()

_DIM_QUERY = """
    SELECT
        c.church_id AS id,
        c.name,
        c.address,
        c.city,
        c.state,
        c.denomination,
        c.service_times,
        c.website,
        c.phone,
        c.language,
        c.cultural_background,
        c.website_summary,
        c.extracted_tags,
        c.latitude,
        c.longitude,
        ROUND(AVG(r.rating), 1)               AS avg_rating,
        COUNT(r.review_id)                    AS review_count,
        AVG(r.worship_energy)                 AS avg_worship_energy,
        AVG(r.community_warmth)               AS avg_community_warmth,
        AVG(r.sermon_depth)                   AS avg_sermon_depth,
        AVG(r.childrens_programs)             AS avg_childrens_programs,
        AVG(r.theological_openness)           AS avg_theological_openness,
        AVG(r.facilities)                     AS avg_facilities
    FROM Churches c
    LEFT JOIN Reviews r ON c.church_id = r.church_id
"""


def _safe_keys(row, key: str):
    """Return row[key] if the row has that column, else None.

    sqlite3.Row exposes columns via mapping access but raises IndexError on
    unknown keys. The /similar query has a different column set than _DIM_QUERY,
    so we tolerate either shape.
    """
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _row_to_church(row, include_dims: bool = False) -> dict:
    dims = {
        "worship_energy": row["avg_worship_energy"],
        "community_warmth": row["avg_community_warmth"],
        "sermon_depth": row["avg_sermon_depth"],
        "childrens_programs": row["avg_childrens_programs"],
        "theological_openness": row["avg_theological_openness"],
        "facilities": row["avg_facilities"],
    }
    church = {
        "id": row["id"],
        "name": row["name"],
        "address": row["address"],
        "city": row["city"],
        "state": row["state"],
        "denomination": row["denomination"],
        "service_times": row["service_times"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "avg_rating": row["avg_rating"],
        "review_count": row["review_count"],
        "website": row["website"] or None,
        "phone": row["phone"] or None,
        "language": row["language"] or None,
        "cultural_background": row["cultural_background"] or None,
        "tags": compute_tags(dims, row["review_count"] or 0),
        "website_summary": _safe_keys(row, "website_summary") or None,
        "extracted_tags": (json.loads(_safe_keys(row, "extracted_tags")) if _safe_keys(row, "extracted_tags") else None),
    }
    if include_dims:
        church["dimensions"] = {k: (round(v, 2) if v is not None else None) for k, v in dims.items()}
    return church


@router.get("/churches")
def list_churches(
    city: str = "",
    state: str = "",
    zip_code: str = "",
    limit: int = 50,
    offset: int = 0,
    db: Database = Depends(get_db),
):
    if zip_code:
        query = _DIM_QUERY + "WHERE c.zip_code = ? GROUP BY c.church_id LIMIT ? OFFSET ?"
        rows = db.execute_query(query, (zip_code, limit, offset))
    else:
        query = (
            _DIM_QUERY
            + "WHERE LOWER(c.city) = LOWER(?) AND LOWER(c.state) = LOWER(?)"
            + " GROUP BY c.church_id ORDER BY review_count DESC LIMIT ? OFFSET ?"
        )
        rows = db.execute_query(query, (city, state, limit, offset))
    return [_row_to_church(row) for row in rows]


@router.get("/churches/{church_id}/similar")
def get_similar_churches(church_id: int, db: Database = Depends(get_db)):
    target = db.execute_query(_DIM_QUERY + "WHERE c.church_id = ? GROUP BY c.church_id", (church_id,))
    if not target:
        raise HTTPException(status_code=404, detail="Church not found")
    query = """
        SELECT
            c.church_id AS id, c.name, c.address, c.city, c.state,
            c.denomination, c.service_times, c.website, c.phone,
            c.language, c.cultural_background,
            c.latitude, c.longitude,
            ROUND(AVG(r.rating), 1)               AS avg_rating,
            COUNT(r.review_id)                    AS review_count,
            AVG(r.worship_energy)                 AS avg_worship_energy,
            AVG(r.community_warmth)               AS avg_community_warmth,
            AVG(r.sermon_depth)                   AS avg_sermon_depth,
            AVG(r.childrens_programs)             AS avg_childrens_programs,
            AVG(r.theological_openness)           AS avg_theological_openness,
            AVG(r.facilities)                     AS avg_facilities,
            (
                (COALESCE(AVG(r.worship_energy),       0) - COALESCE(t.we,  0)) *
                (COALESCE(AVG(r.worship_energy),       0) - COALESCE(t.we,  0))
              + (COALESCE(AVG(r.community_warmth),     0) - COALESCE(t.cw,  0)) *
                (COALESCE(AVG(r.community_warmth),     0) - COALESCE(t.cw,  0))
              + (COALESCE(AVG(r.sermon_depth),         0) - COALESCE(t.sd,  0)) *
                (COALESCE(AVG(r.sermon_depth),         0) - COALESCE(t.sd,  0))
              + (COALESCE(AVG(r.childrens_programs),   0) - COALESCE(t.cp,  0)) *
                (COALESCE(AVG(r.childrens_programs),   0) - COALESCE(t.cp,  0))
              + (COALESCE(AVG(r.theological_openness), 0) - COALESCE(t.to_, 0)) *
                (COALESCE(AVG(r.theological_openness), 0) - COALESCE(t.to_, 0))
              + (COALESCE(AVG(r.facilities),           0) - COALESCE(t.fac, 0)) *
                (COALESCE(AVG(r.facilities),           0) - COALESCE(t.fac, 0))
            ) AS dist_sq
        FROM Churches c
        JOIN Reviews r ON c.church_id = r.church_id
        JOIN (
            SELECT
                COALESCE(AVG(worship_energy),       0) AS we,
                COALESCE(AVG(community_warmth),     0) AS cw,
                COALESCE(AVG(sermon_depth),         0) AS sd,
                COALESCE(AVG(childrens_programs),   0) AS cp,
                COALESCE(AVG(theological_openness), 0) AS to_,
                COALESCE(AVG(facilities),           0) AS fac
            FROM Reviews WHERE church_id = ?
        ) t
        WHERE c.church_id != ?
        GROUP BY c.church_id
        ORDER BY dist_sq ASC
        LIMIT 3
    """
    rows = db.execute_query(query, (church_id, church_id))
    return [_row_to_church(row) for row in rows]


@router.get("/churches/{church_id}")
def get_church(church_id: int, db: Database = Depends(get_db)):
    query = _DIM_QUERY + "WHERE c.church_id = ? GROUP BY c.church_id"
    rows = db.execute_query(query, (church_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Church not found")
    return _row_to_church(rows[0], include_dims=True)


@router.post("/churches/{church_id}/enrich")
def enrich_church(church_id: int, db: Database = Depends(get_db)):
    """Trigger Google Places enrichment for a church. Idempotent and cap-safe."""
    con = sqlite3.connect(db.db_path)
    con.row_factory = sqlite3.Row
    try:
        result = enrichment.enrich(church_id, con)
    finally:
        con.close()
    if result is None:
        # Either already enriched with no data, cap reached, or no API key
        row = db.execute_query(
            "SELECT google_photos, google_hours FROM Churches WHERE church_id = ?",
            (church_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Church not found")
        r = row[0]
        return {
            "photos": json.loads(r["google_photos"]) if r["google_photos"] else [],
            "hours": json.loads(r["google_hours"]) if r["google_hours"] else [],
        }
    return result
