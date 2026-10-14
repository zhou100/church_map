"""Admin router for the Phase B crawl pipeline.

Endpoints are X-Crawl-Token-protected (shared static token between Render env
and GH Actions secret). Not behind GSI auth — the cron caller doesn't have a
Google session.

Endpoints intentionally return quickly: each call processes one batch of
the configured size and exits. The cron schedule drives volume.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.db import pool
from backend.db.repository import CrawlBusy, CrawlRepository
from backend.scrapers_v2 import extract as extract_mod
from backend.scrapers_v2 import fetch as fetch_mod
from backend.scrapers_v2 import tag as tag_mod
from backend.scrapers_v2.prompts.website_v3 import MODEL, PROMPT_VERSION
from backend.scrapers_v2.r2 import R2Client, R2Error

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/crawl", tags=["admin-crawl"])

DEFAULT_FETCH_FRESH_DAYS = 30
FETCH_RUNNER_TIMEOUT_S = 300
FETCH_REQUEST_TIMEOUT_S = 330
FETCH_CLEANUP_TIMEOUT_S = 10
FETCH_LEASE_S = 540


def require_crawl_token(x_crawl_token: str = Header(default="")) -> None:
    expected = os.environ.get("CRAWL_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="crawl token not configured")
    if not secrets.compare_digest(x_crawl_token, expected):
        raise HTTPException(status_code=403, detail="invalid crawl token")


async def _run_stage(stage: str, batch_size: int, runner, request_key: str | None = None) -> dict | JSONResponse:
    if stage != 'fetch':
        return await _run_stage_impl(stage, batch_size, runner, request_key)
    try:
        async with asyncio.timeout(FETCH_REQUEST_TIMEOUT_S):
            return await _run_stage_impl(stage, batch_size, runner, request_key)
    except TimeoutError:
        raise HTTPException(status_code=504, detail='fetch request exceeded its time budget')


async def _run_stage_impl(stage: str, batch_size: int, runner, request_key: str | None) -> dict | JSONResponse:
    """Wrap a stage runner in a crawl_runs row + try/except.

    Important: psycopg's pool.connection() context rolls back on exception
    exit by default. If we wrote the error row inside the same `async with`
    and then raised, the row would vanish and `/status` would never show the
    failed invocation. So we commit the start_run on entry, commit the
    finish_run before raising, and only then convert to HTTPException.

    One failure cannot be recorded at all: if the database is unreachable
    there is nowhere to write "the database was unreachable". That happened
    on 2026-07-27 — a bare 500 with no crawl_runs row, so `/status` and
    `/api/stats` both kept reporting a clean pipeline while the scheduled run
    went red. It still can't be recorded, but it can be *named*: a 503 whose
    detail says which step failed, rather than a generic 500 that could have
    come from anywhere in the batch. `/api/stats` reports staleness from the
    age of the last success, which no absent row can fake.
    """
    error_payload: tuple[str, str] | None = None
    recorded = False   # did a crawl_runs row make it to disk?
    try:
        async with pool.acquire() as con:
            repo = CrawlRepository(con)
            if stage == 'fetch':
                await repo.bound_fetch_transaction()
                run, replayed = await repo.claim_run(
                    stage, batch_size, request_key, lease_seconds=FETCH_LEASE_S,
                )
                if replayed:
                    await con.commit()
                    payload = {
                        **run.get('metadata', {}), 'run_id': run['id'], 'stage': stage,
                        'status': run['status'], 'replayed': True,
                        **{k: run[k] for k in ('rows_processed', 'rows_ok', 'rows_error', 'rows_skipped')},
                    }
                    if run['status'] in ('running', 'error'):
                        return JSONResponse(payload, status_code=202 if run['status'] == 'running' else 500)
                    return payload
                run_id = run['id']
            else:
                run_id = await repo.start_run(
                    stage, batch_size, triggered_by="github-actions"
                )
            # Commit so the run row exists even if the runner crashes before
            # finish_run runs (e.g., OOM, SIGTERM during a long batch).
            await con.commit()
            recorded = True
            try:
                if stage == 'fetch':
                    # Includes target selection, storage and DB work. Shorter
                    # than both the durable lease and the caller's 360s limit.
                    async with asyncio.timeout(FETCH_RUNNER_TIMEOUT_S):
                        counts = await runner(repo, run_id)
                    await repo.bound_fetch_transaction()
                    await repo.update_run_progress(run_id, counts)
                else:
                    counts = await runner(repo, run_id)
                status = "partial" if (
                    counts['rows_error'] or counts.get('pages_error') or counts.get('budget_exhausted')
                ) else "ok"
                await repo.finish_run(
                    run_id,
                    status=status,
                    rows_processed=counts["rows_processed"],
                    rows_ok=counts["rows_ok"],
                    rows_error=counts["rows_error"],
                )
                if stage == 'fetch':
                    await repo.release_run(run_id)
                await con.commit()
                return {"run_id": run_id, "stage": stage, "status": status, **counts}
            except (Exception, asyncio.CancelledError) as e:
                log.exception("%s stage failed: %s", stage, e)
                # A failed SQL statement leaves the transaction aborted.
                # Roll it back before recording the error, preserving already
                # committed churches and their counters.
                async with asyncio.timeout(FETCH_CLEANUP_TIMEOUT_S):
                    await con.rollback()
                    if stage == 'fetch':
                        await repo.bound_fetch_transaction()
                    await repo.fail_run(run_id, f"{type(e).__name__}: {str(e)[:500]}")
                    if stage == 'fetch':
                        await repo.release_run(run_id)
                    await con.commit()
                if isinstance(e, asyncio.CancelledError):
                    raise
                error_payload = (stage, type(e).__name__)
    except CrawlBusy as e:
        raise HTTPException(status_code=409, detail=str(e), headers={'Retry-After': '60'})
    except HTTPException:
        raise
    except Exception as e:
        # Only reachable while `recorded` is False — acquiring the connection,
        # start_run, or its commit. Nothing was written, so this run is
        # invisible to /status by construction; say so in the response instead
        # of returning a bare 500 that looks like a batch failure.
        if recorded:
            raise
        log.exception("%s stage could not reach the database", stage)
        raise HTTPException(
            status_code=503,
            detail=(
                f"{stage} could not reach the database ({type(e).__name__}); "
                "no crawl_runs row was written, so this failure is invisible "
                "to /status — see /api/stats crawl.stages for staleness"
            ),
        )

    # Out of the connection context — safe to raise without losing the row.
    if error_payload is not None:
        raise HTTPException(
            status_code=500,
            detail=f"{error_payload[0]} failed: {error_payload[1]}",
        )


@router.post("/fetch", dependencies=[Depends(require_crawl_token)])
async def crawl_fetch(
    batch: int = Query(default=5, ge=1, le=25),
    fresh_days: int = Query(default=DEFAULT_FETCH_FRESH_DAYS, ge=1, le=365),
    request_key: str | None = Header(default=None, alias='Idempotency-Key', min_length=1, max_length=128),
):
    try:
        r2 = R2Client()
    except R2Error as e:
        raise HTTPException(status_code=503, detail=f"R2 not configured: {e}")

    async def runner(repo: CrawlRepository, run_id: int) -> dict:
        return await fetch_mod.run_fetch_batch(
            repo, r2, batch_size=batch, fresh_days=fresh_days, crawl_run_id=run_id,
        )

    return await _run_stage("fetch", batch, runner, request_key=request_key)


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


@router.post("/requeue", dependencies=[Depends(require_crawl_token)])
async def crawl_requeue(
    limit: int = Query(default=200, ge=1, le=5000),
    dry_run: bool = Query(default=True),
):
    """Re-queue churches whose extraction predates the current prompt/model.

    Needed because the extract stage selects on `extract_status`, never on
    prompt version — so a prompt or model change applies to new extractions
    only, and existing rows keep whatever they were extracted under. This
    puts them back in the normal queue; the scheduled extract stage then
    drains it at its usual batch size, with its usual bookkeeping.

    Defaults to `dry_run=true`. Re-extraction costs real money per church,
    so the safe call is the one that only counts, and spending requires
    saying so explicitly.

    `limit` bounds churches, not artifacts — run it in passes and watch
    `/api/stats` (or `/status`) between them rather than queueing the whole
    corpus at once.
    """
    async with pool.acquire() as con:
        repo = CrawlRepository(con)
        counts = await repo.count_stale_extractions(PROMPT_VERSION, MODEL)
        if dry_run:
            return {
                "dry_run": True,
                "current_prompt_version": PROMPT_VERSION,
                "current_model": MODEL,
                "stale_churches": counts["total"],
                "awaiting_queue": counts["awaiting_queue"],
                "would_requeue_churches": min(counts["awaiting_queue"], limit),
            }
        church_ids = await repo.requeue_stale_extractions(
            PROMPT_VERSION, MODEL, limit=limit
        )
        await con.commit()

    unique = sorted(set(church_ids))
    log.info(
        "requeued %d artifacts across %d churches for re-extraction (%s / %s)",
        len(church_ids), len(unique), PROMPT_VERSION, MODEL,
    )
    return {
        "dry_run": False,
        "current_prompt_version": PROMPT_VERSION,
        "current_model": MODEL,
        # Size of the whole backfill. Does NOT drop when you re-queue — a
        # church stays stale until the extract stage rewrites its row.
        "stale_churches": counts["total"],
        "requeued_churches": len(unique),
        "requeued_artifacts": len(church_ids),
        # What is left to hand to the pipeline. This is the one that falls
        # per pass; run again until it reaches zero.
        "awaiting_queue_after": max(0, counts["awaiting_queue"] - len(unique)),
    }


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
                "heartbeat_at": r["heartbeat_at"].isoformat() if r.get("heartbeat_at") else None,
                "progress_at": r["progress_at"].isoformat() if r.get("progress_at") else None,
            }
            for r in runs
        ]
    }
