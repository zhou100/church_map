"""Public pipeline stats — aggregate counts only, no token required.

`/api/admin/crawl/status` answers "how is the crawl doing?" but it is
token-gated and per-run, so from outside the project there has been no way
to tell a working pipeline from a dead one. That is not a hypothetical: the
scheduled crawl was auto-disabled on 2026-07-08 and nobody noticed for 8
days, because silence and success look identical from the outside.

This endpoint exposes only aggregates — totals, percentages, last
successful run per stage — so it needs no auth. Nothing here identifies a
church.

The response is cached in-process for CACHE_TTL_S. The queries are full
scans of a 134k-row table; cheap, but this is a public endpoint and there
is no reason to run them per request.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from backend.db import pool
from backend.db.repository import StatsRepository
from backend.scrapers_v2.prompts.website_v3 import MODEL, PROMPT_VERSION

router = APIRouter()

CACHE_TTL_S = 300

# Mirrors the CHECK constraint on crawl_runs.stage (migrations/0004).
CRAWL_STAGES = ("fetch", "extract", "tag")

# How long a stage may go without a successful run before it counts as
# stale. Cadence comes from the crons in .github/workflows/crawl.yml (fetch
# every 4h, extract twice daily, tag daily), roughly doubled to absorb one
# missed run plus GitHub's scheduling drift.
#
# This exists because "no errors" is not the same as "working". A stage can
# fail before it ever writes a crawl_runs row — if the database is
# unreachable, `_run_stage` cannot record that the database was unreachable
# — so the error counter stays at zero while nothing succeeds. That is the
# same shape as the 2026-07-08 outage: silence reading as success. Age since
# the last *success* is the signal that cannot be faked by an absence.
STAGE_MAX_AGE_S = {
    "fetch": 8 * 3600,
    "extract": 24 * 3600,
    "tag": 48 * 3600,
}

_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _pct(part: int, whole: int) -> float | None:
    """Percentage to one decimal, or None when the denominator is zero."""
    if not whole:
        return None
    return round(100.0 * part / whole, 1)


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def build_stats(
    counts: dict,
    by_version: list[dict],
    health: dict,
    *,
    current_prompt_version: str = PROMPT_VERSION,
    current_model: str = MODEL,
    now: datetime | None = None,
) -> dict:
    """Shape repository rows into the public response.

    Pure — no DB, no clock unless one is passed — so the arithmetic that
    anyone reads off a status page is unit-testable.
    """
    total = counts.get("total") or 0
    with_website = counts.get("with_website") or 0
    extracted = counts.get("extracted") or 0

    # "Current" means prompt version AND model, matching the staleness
    # predicate the re-queue uses. Version alone reported churches as current
    # that the re-queue would immediately pick up.
    versions = [
        {
            "version": row["version"],
            "model": row.get("model"),
            "count": row["count"],
            "current": (
                row["version"] == current_prompt_version
                and row.get("model") == current_model
            ),
        }
        for row in by_version
    ]
    # Churches extracted under an older prompt or model. Re-extracting them is
    # a deliberate backfill, not something the pipeline does on its own: the
    # extract stage selects on artifact status, never on prompt version.
    stale = sum(v["count"] for v in versions if not v["current"])

    window = {row["status"]: row["count"] for row in health.get("window", [])}

    # Every stage always appears, even one that has never succeeded. The query
    # groups over rows that exist, so a stage with no 'ok' run comes back
    # missing entirely — and a missing key reads as "fine" to whatever renders
    # this, which is the exact failure this endpoint exists to surface. Absent
    # becomes an explicit null.
    seen = {row["stage"]: row.get("last_success") for row in health.get("last_success", [])}
    last_success = {stage: _iso(seen.get(stage)) for stage in CRAWL_STAGES}

    at = now or datetime.now(timezone.utc)
    stages = {}
    for stage in CRAWL_STAGES:
        ts = seen.get(stage)
        age = int((at - ts).total_seconds()) if isinstance(ts, datetime) else None
        stages[stage] = {
            "last_success": _iso(ts),
            "age_seconds": age,
            "max_age_seconds": STAGE_MAX_AGE_S[stage],
            # Never having succeeded counts as stale, not as "no opinion".
            "stale": True if age is None else age > STAGE_MAX_AGE_S[stage],
        }
    pipeline_ok = not any(s["stale"] for s in stages.values())

    return {
        "churches": {
            "total": total,
            "with_website": with_website,
            "with_website_pct": _pct(with_website, total),
            "extracted": extracted,
            # Of the churches that *could* be extracted — the honest
            # denominator. Against all 134k it would always look like failure.
            "extracted_pct_of_website": _pct(extracted, with_website),
            "with_summary": counts.get("with_summary") or 0,
            "google_enriched": counts.get("enriched") or 0,
        },
        "extraction": {
            "current_prompt_version": current_prompt_version,
            "by_prompt_version": versions,
            "stale": stale,
            "stale_pct": _pct(stale, extracted),
        },
        "crawl": {
            # True only if every stage has succeeded recently enough. Do not
            # infer health from `runs.error == 0`: a stage that dies before
            # writing its crawl_runs row contributes no error at all.
            "pipeline_ok": pipeline_ok,
            "stages": stages,
            "last_success": last_success,
            "runs": {
                "window_days": health.get("window_days"),
                "ok": window.get("ok", 0),
                "error": window.get("error", 0),
                "partial": window.get("partial", 0),
                "running": window.get("running", 0),
            },
        },
        "generated_at": at.isoformat(),
        "cache_ttl_seconds": CACHE_TTL_S,
    }


@router.get("/stats")
async def stats() -> dict:
    if _cache["value"] is not None and (time.monotonic() - _cache["at"]) < CACHE_TTL_S:
        return _cache["value"]

    async with pool.acquire() as con:
        repo = StatsRepository(con)
        counts = await repo.church_counts()
        by_version = await repo.extraction_by_prompt_version()
        health = await repo.crawl_health()

    value = build_stats(counts, by_version, health)
    _cache["at"] = time.monotonic()
    _cache["value"] = value
    return value
