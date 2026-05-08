"""
Auth router. The single endpoint /api/auth/verify accepts a Google ID token,
verifies it via tokeninfo, upserts the user row, and returns the canonical
user record. Token verification logic lives in backend.auth so reviews
router shares the same code path.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.auth import verify_google_token
from backend.db import pool
from backend.db.repository import UserRepository

router = APIRouter()


class TokenBody(BaseModel):
    token: str


@router.post("/auth/verify")
async def auth_verify(body: TokenBody):
    info = await verify_google_token(body.token)
    async with pool.acquire() as con:
        async with con.transaction():
            user = await UserRepository(con).upsert(
                google_id=info["sub"],
                email=info.get("email", ""),
                name=info.get("name", ""),
                avatar_url=info.get("picture", ""),
            )
    return user
