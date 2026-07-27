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
from backend.db.repository import CrawlRepository, StatsRepository
from backend.scrapers_v2.prompts.website_v3 import MODEL, PROMPT_VERSION

router = APIRouter()

CACHE_TTL_S = 300

# Mirrors the CHECK constraint on crawl_runs.stage (migrations/0004).
CRAWL_STAGES = ("fetch", "extract", "tag")

# Buckets from StatsRepository.extraction_status_breakdown, always all present.
# Fixed rather than whatever the query happened to return, for the same reason
# the stages dict is: a missing key reads as "none of those", and "no failures"
# is exactly the reading this endpoint exists to stop being accidental.
#
# Ordered by what they mean for the operator, not by frequency:
#   ok         extracted fine
#   no_html    R2 has no page behind the artifact — needs re-FETCHING, not
#              re-extracting; re-queueing these does nothing
#   no_text    page was read and held nothing usable — terminal, correctly
#   error      model output failed validation — terminal, correctly
#   transient  failed recoverably; the next run retries it, no action needed
#   unknown    attempted before extracted_status existed
#   other      a status string none of the above match — a code change landed
#              without updating this list
EXTRACT_STATUSES = (
    "ok", "no_html", "no_text", "error", "transient", "unknown", "other",
)

# How long a stage may go without making progress before it counts as stale.
# Cadence comes from the crons in .github/workflows/crawl.yml (fetch every
# 4h, extract 3x daily, tag daily). Each budget clears two cadences, because
# after a failure the next attempt is one cadence out — a budget under 2x
# means a single miss always alerts, which is a broken alarm, not a tight one.
#
# This exists because "no errors" is not the same as "working". A stage can
# fail before it ever writes a crawl_runs row — if the database is
# unreachable, `_run_stage` cannot record that the database was unreachable
# — so the error counter stays at zero while nothing succeeds. That is the
# same shape as the 2026-07-08 outage: silence reading as success. Age since
# the last *progress* is the signal that cannot be faked by an absence.
STAGE_MAX_AGE_S = {
    # 12h, not 8h: fetch runs every 4h, and at 8h a *single* failed run always
    # trips pipeline_ok — the retry is 4h out, so age crosses 8h before
    # recovery is even possible. Observed 2026-07-27, when one transient
    # failure at 04:04 held pipeline_ok false for hours with nothing wrong.
    # Three cadences tolerates one miss and still catches a real outage inside
    # half a day.
    "fetch": 12 * 3600,
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
    by_status: list[dict] | None = None,
    stale_counts: dict | None = None,
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

    # Why extraction attempts ended. `extracted_at` is stamped by failures too,
    # so `churches.extracted` above is attempts, not successes — this is the
    # split, and `attempts.ok` is the honest headline.
    seen_status = {row["status"]: row["count"] for row in (by_status or [])}
    attempts = {s: seen_status.get(s, 0) for s in EXTRACT_STATUSES}
    attempted = sum(attempts.values())
    failed = attempted - attempts["ok"]

    window = {row["status"]: row["count"] for row in health.get("window", [])}

    # Every stage always appears, even one that has never succeeded. The query
    # groups over rows that exist, so a stage with no 'ok' run comes back
    # missing entirely — and a missing key reads as "fine" to whatever renders
    # this, which is the exact failure this endpoint exists to surface. Absent
    # becomes an explicit null.
    rows = health.get("last_success", [])
    seen = {row["stage"]: row.get("last_success") for row in rows}
    # A run that finished and got at least one row through. Staleness is
    # measured against this, not against the last flawless run: `status='ok'`
    # means zero rows failed, so one bad row in a batch makes it 'partial' and
    # the strict clock stops. During the v3.1 backfill, whose batches fail on
    # a real fraction of churches, that clock would stop for the duration and
    # report a stage-wide outage that isn't happening.
    progress = {row["stage"]: row.get("last_progress") for row in rows}
    last_success = {stage: _iso(seen.get(stage)) for stage in CRAWL_STAGES}

    at = now or datetime.now(timezone.utc)
    stages = {}
    for stage in CRAWL_STAGES:
        ts = progress.get(stage)
        age = int((at - ts).total_seconds()) if isinstance(ts, datetime) else None
        stages[stage] = {
            # Last completely clean run — kept because "nothing has failed in
            # this stage since X" is worth knowing, just not worth alerting on.
            "last_success": _iso(seen.get(stage)),
            "last_progress": _iso(ts),
            "age_seconds": age,
            "max_age_seconds": STAGE_MAX_AGE_S[stage],
            # Never having made progress counts as stale, not as "no opinion".
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
            "current_model": current_model,
            "by_prompt_version": versions,
            "stale": stale,
            "stale_pct": _pct(stale, extracted),
            # What the re-queue can still hand to the pipeline: stale, not
            # already queued, and holding an artifact worth re-reading. The
            # backfill runbook says to repeat until this hits zero, and until
            # now it took a token to read. Watch it against `stale`: the two
            # falling together is progress, `awaiting_queue` reaching zero
            # while `stale` sits still is the backfill failing to a halt.
            "awaiting_queue": (stale_counts or {}).get("awaiting_queue"),
            "attempts": attempts,
            "attempted": attempted,
            "failed": failed,
            "failed_pct": _pct(failed, attempted),
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
        by_status = await repo.extraction_status_breakdown()
        health = await repo.crawl_health()
        # Deliberately the re-queue's own counter rather than a reimplementation
        # of it here. #20 was two queries answering "is this church stale?"
        # differently and disagreeing by 150 churches; sharing the method makes
        # that class of drift impossible rather than merely fixed.
        stale_counts = await CrawlRepository(con).count_stale_extractions(
            PROMPT_VERSION, MODEL
        )

    value = build_stats(
        counts, by_version, health,
        by_status=by_status, stale_counts=stale_counts,
    )
    _cache["at"] = time.monotonic()
    _cache["value"] = value
    return value
