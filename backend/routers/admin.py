"""Admin router for the Phase B crawl pipeline.

Endpoints are X-Crawl-Token-protected (shared static token between Render env
and GH Actions secret). Not behind GSI auth — the cron caller doesn't have a
Google session.

Endpoints intentionally return quickly: each call processes one batch of
the configured size and exits. The cron schedule drives volume.
"""
from __future__ import annotations

import logging
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from backend.db import pool
from backend.db.repository import CrawlRepository
from backend.scrapers_v2 import extract as extract_mod
from backend.scrapers_v2 import fetch as fetch_mod
from backend.scrapers_v2 import tag as tag_mod
from backend.scrapers_v2.r2 import R2Client, R2Error

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/crawl", tags=["admin-crawl"])

DEFAULT_FETCH_FRESH_DAYS = 30


def require_crawl_token(x_crawl_token: str = Header(default="")) -> None:
    expected = os.environ.get("CRAWL_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="crawl token not configured")
    if not secrets.compare_digest(x_crawl_token, expected):
        raise HTTPException(status_code=403, detail="invalid crawl token")


async def _run_stage(stage: str, batch_size: int, runner) -> dict:
    """Wrap a stage runner in a crawl_runs row + try/except."""
    async with pool.acquire() as con:
        repo = CrawlRepository(con)
        run_id = await repo.start_run(
            stage, batch_size, triggered_by="github-actions"
        )
        try:
            counts = await runner(repo, run_id)
            status = "ok" if counts["rows_error"] == 0 else "partial"
            await repo.finish_run(
                run_id,
                status=status,
                rows_processed=counts["rows_processed"],
                rows_ok=counts["rows_ok"],
                rows_error=counts["rows_error"],
            )
            return {"run_id": run_id, "stage": stage, "status": status, **counts}
        except Exception as e:
            log.exception("%s stage failed: %s", stage, e)
            await repo.finish_run(
                run_id,
                status="error",
                rows_processed=0,
                rows_ok=0,
                rows_error=0,
                error=f"{type(e).__name__}: {str(e)[:500]}",
            )
            raise HTTPException(status_code=500, detail=f"{stage} failed: {type(e).__name__}")


@router.post("/fetch", dependencies=[Depends(require_crawl_token)])
async def crawl_fetch(
    batch: int = Query(default=50, ge=1, le=500),
    fresh_days: int = Query(default=DEFAULT_FETCH_FRESH_DAYS, ge=1, le=365),
):
    try:
        r2 = R2Client()
    except R2Error as e:
        raise HTTPException(status_code=503, detail=f"R2 not configured: {e}")

    async def runner(repo: CrawlRepository, run_id: int) -> dict:
        return await fetch_mod.run_fetch_batch(
            repo, r2, batch_size=batch, fresh_days=fresh_days, crawl_run_id=run_id,
        )

    return await _run_stage("fetch", batch, runner)


@router.post("/extract", dependencies=[Depends(require_crawl_token)])
async def crawl_extract(
    batch: int = Query(default=20, ge=1, le=200),
):
    try:
        r2 = R2Client()
    except R2Error as e:
        raise HTTPException(status_code=503, detail=f"R2 not configured: {e}")

    async def runner(repo: CrawlRepository, _run_id: int) -> dict:
        return await extract_mod.run_extract_batch(repo, r2, batch_size=batch)

    return await _run_stage("extract", batch, runner)


@router.post("/tag", dependencies=[Depends(require_crawl_token)])
async def crawl_tag(
    batch: int = Query(default=500, ge=1, le=5000),
    force: bool = Query(default=False),
):
    async def runner(repo: CrawlRepository, _run_id: int) -> dict:
        return await tag_mod.run_tag_batch(repo, batch_size=batch, force=force)

    return await _run_stage("tag", batch, runner)


@router.get("/status", dependencies=[Depends(require_crawl_token)])
async def crawl_status(limit: int = Query(default=20, ge=1, le=100)):
    async with pool.acquire() as con:
        repo = CrawlRepository(con)
        runs = await repo.recent_runs(limit=limit)
    return {
        "runs": [
            {
                **r,
                "started_at": r["started_at"].isoformat() if r.get("started_at") else None,
                "finished_at": r["finished_at"].isoformat() if r.get("finished_at") else None,
            }
            for r in runs
        ]
    }
