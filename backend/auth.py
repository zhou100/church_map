"""
Single source of truth for Google Identity Services token verification.

Phase A consolidates two near-duplicate implementations that drifted apart
between routers/auth.py and routers/reviews.py. The behavior is the active
production design from CLAUDE.md: GSI in browser → POST /api/auth/verify →
Google `tokeninfo` on every protected request. No JWT lib, no session store.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import Header, HTTPException

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


async def verify_google_token(token: str) -> dict:
    """
    Verify a Google ID token via Google's tokeninfo endpoint and return the
    decoded claims. Raises HTTPException(401) on any failure.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(TOKENINFO_URL, params={"id_token": token})
    if r.status_code != 200:
        raise HTTPException(401, "Invalid or expired token, please sign in again")
    info = r.json()
    if GOOGLE_CLIENT_ID and info.get("aud") != GOOGLE_CLIENT_ID:
        raise HTTPException(401, "Token audience mismatch")
    return info


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """
    FastAPI dependency that extracts and verifies the Bearer token.
    Returned dict shape matches what the reviews router has historically
    consumed: google_id, name, avatar_url, email.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in to leave a review")
    token = authorization.split(" ", 1)[1]
    info = await verify_google_token(token)
    return {
        "google_id": info["sub"],
        "name": info.get("name", ""),
        "avatar_url": info.get("picture", ""),
        "email": info.get("email", ""),
    }
