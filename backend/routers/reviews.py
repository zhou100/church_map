"""
Reviews router. Uses ReviewRepository + UserRepository against the async
Postgres pool. Auth comes from backend.auth (consolidated).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.db import pool
from backend.db.repository import ReviewRepository, UserRepository

router = APIRouter()


class ReviewCreate(BaseModel):
    church_id: int
    rating: float = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    worship_energy: Optional[float] = Field(None, ge=1, le=5)
    community_warmth: Optional[float] = Field(None, ge=1, le=5)
    sermon_depth: Optional[float] = Field(None, ge=1, le=5)
    childrens_programs: Optional[float] = Field(None, ge=1, le=5)
    theological_openness: Optional[float] = Field(None, ge=1, le=5)
    facilities: Optional[float] = Field(None, ge=1, le=5)


@router.get("/reviews/{church_id}")
async def get_reviews(church_id: int):
    async with pool.acquire() as con:
        reviews = await ReviewRepository(con).list_by_church(church_id)

    dim_keys = [
        "worship_energy",
        "community_warmth",
        "sermon_depth",
        "childrens_programs",
        "theological_openness",
        "facilities",
    ]
    agg = {}
    for key in dim_keys:
        vals = [r[key] for r in reviews if r.get(key) is not None]
        agg[key] = round(sum(vals) / len(vals), 2) if vals else None

    return {"dimensions": agg, "reviews": reviews}


@router.post("/reviews", status_code=201)
async def submit_review(
    payload: ReviewCreate,
    user: dict = Depends(get_current_user),
):
    async with pool.acquire() as con:
        async with con.transaction():
            user_row = await UserRepository(con).upsert(
                google_id=user["google_id"],
                email=user.get("email", ""),
                name=user["name"],
                avatar_url=user["avatar_url"],
            )
            try:
                review_id = await ReviewRepository(con).insert(
                    church_id=payload.church_id,
                    rating=payload.rating,
                    comment=payload.comment,
                    worship_energy=payload.worship_energy,
                    community_warmth=payload.community_warmth,
                    sermon_depth=payload.sermon_depth,
                    childrens_programs=payload.childrens_programs,
                    theological_openness=payload.theological_openness,
                    facilities=payload.facilities,
                    user_id=user_row["user_id"],
                    reviewer_name=user["name"],
                    reviewer_avatar=user["avatar_url"],
                )
            except Exception as e:
                raise HTTPException(500, f"Failed to insert review: {e}")
    return {"review_id": review_id}
