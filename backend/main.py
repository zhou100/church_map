"""
FastAPI app entrypoint.

Phase A changes vs. the SQLite-era main.py:
  * Lifespan replaces deprecated @app.on_event hooks. Pool opens on startup,
    closes on shutdown.
  * READ_ONLY middleware short-circuits POST/PUT/PATCH/DELETE with 503 when
    the env var is set. Used during cutover to lock the old Fly machine
    while the new Render machine takes over writes; backstops the frontend
    banner so a stale tab cannot silently lose a review.
  * CORS is locked to known frontend origins instead of the previous "*".
"""
from backend.env_loader import load_env_local

load_env_local()

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.db import pool
from backend.routers import admin, auth, churches, reviews, stats

READ_ONLY = os.environ.get("READ_ONLY", "0") == "1"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# /api/health and /api/auth/verify stay live during READ_ONLY cutovers so
# the healthcheck keeps passing and so a still-loaded frontend can detect
# the signed-in user. The users upsert inside /auth/verify is tolerable; it
# does not affect the user-visible review feed.
READONLY_EXEMPT_PATHS = {"/api/health", "/api/auth/verify"}

ALLOWED_ORIGINS = [
    "https://churchmap.vercel.app",
]
ALLOWED_ORIGIN_REGEX = r"https://churchmap-[a-z0-9-]+\.vercel\.app"
if os.environ.get("ENV") != "production":
    ALLOWED_ORIGINS += [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open_pool()
    try:
        yield
    finally:
        await pool.close_pool()


app = FastAPI(title="HolyHub API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def read_only_guard(request: Request, call_next):
    if (
        READ_ONLY
        and request.method in WRITE_METHODS
        and request.url.path not in READONLY_EXEMPT_PATHS
    ):
        return JSONResponse(
            status_code=503,
            content={"detail": "ChurchMap is read-only during a database upgrade. Try again in a few minutes."},
            headers={"Retry-After": "300"},
        )
    return await call_next(request)


app.include_router(churches.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(stats.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok", "read_only": READ_ONLY}
