"""Shaping logic for the public /api/stats endpoint.

Pure arithmetic, no DB — the numbers a status page reports are exactly the
kind of thing that goes quietly wrong, so they get tested directly.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.routers.stats import _pct, build_stats

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)

COUNTS = {
    "total": 134_000,
    "with_website": 52_000,
    "extracted": 1_200,
    "with_summary": 1_100,
    "enriched": 5_400,
}
CURRENT_V = "2026-07-24.v3.1"
CURRENT_M = "google/gemini-2.5-flash-lite"

BY_VERSION = [
    {"version": "2026-05-08.v3", "model": "google/gemini-2.5-flash", "count": 1_180},
    {"version": CURRENT_V, "model": CURRENT_M, "count": 20},
]
# Shaped exactly like crawl_health() really returns: the query groups over
# rows that exist, so a stage with no successful run is ABSENT, not null.
# Verified against a live Postgres — an earlier fixture invented a
# {"stage": "tag", "last_success": None} row the SQL can never produce, and
# that made the test pass while the endpoint dropped the key entirely.
#
# `last_success` (a flawless run) and `last_progress` (a run that got at least
# one row through) come back per stage; a stage whose every run had some row
# fail has a null last_success and a real last_progress.
HEALTH = {
    "last_success": [
        {
            "stage": "fetch",
            "last_success": datetime(2026, 7, 24, 9, 17, tzinfo=timezone.utc),
            "last_progress": datetime(2026, 7, 24, 9, 17, tzinfo=timezone.utc),
        },
        {
            "stage": "extract",
            "last_success": datetime(2026, 7, 24, 6, 37, tzinfo=timezone.utc),
            "last_progress": datetime(2026, 7, 24, 6, 37, tzinfo=timezone.utc),
        },
    ],
    "window": [{"status": "ok", "count": 39}, {"status": "error", "count": 1}],
    "window_days": 7,
}

BY_STATUS = [
    {"status": "ok", "count": 1_050},
    {"status": "no_text", "count": 90},
    {"status": "error", "count": 60},
]
STALE_COUNTS = {"total": 1_180, "awaiting_queue": 300}


def _build(**kw):
    kw.setdefault("current_prompt_version", CURRENT_V)
    kw.setdefault("current_model", CURRENT_M)
    kw.setdefault("by_status", BY_STATUS)
    kw.setdefault("stale_counts", STALE_COUNTS)
    return build_stats(COUNTS, BY_VERSION, HEALTH, now=NOW, **kw)


# --- percentages -----------------------------------------------------------


def test_pct_rounds_to_one_decimal():
    assert _pct(1, 3) == 33.3


def test_pct_of_zero_is_none_not_zero():
    """A missing denominator must not render as "0%" — that reads as a
    failing pipeline when it actually means "no data yet"."""
    assert _pct(0, 0) is None
    assert _pct(5, 0) is None


def test_extraction_pct_uses_website_havers_as_denominator():
    """Against all 134k churches the pipeline would always look broken;
    only churches with a website are extractable at all."""
    out = _build()
    assert out["churches"]["extracted_pct_of_website"] == pytest.approx(2.3, abs=0.05)
    assert out["churches"]["with_website_pct"] == pytest.approx(38.8, abs=0.05)


# --- prompt-version split (this is what sizes a backfill) ------------------


def test_stale_counts_everything_not_on_the_current_prompt():
    out = _build()["extraction"]
    assert out["stale"] == 1_180
    assert out["stale_pct"] == pytest.approx(98.3, abs=0.05)
    assert out["current_prompt_version"] == CURRENT_V


def test_current_version_is_flagged_per_row():
    versions = {v["version"]: v["current"] for v in _build()["extraction"]["by_prompt_version"]}
    assert versions == {"2026-05-08.v3": False, CURRENT_V: True}


def test_same_prompt_on_the_old_model_is_stale():
    """The bug this fixes. The re-queue treats a model change exactly like a
    prompt change, so a row on the right prompt but the wrong model must not
    be reported as current — otherwise /api/stats says the backfill is done
    while the re-queue immediately picks those churches back up."""
    rows = [
        {"version": CURRENT_V, "model": "google/gemini-2.5-flash", "count": 200},
        {"version": CURRENT_V, "model": CURRENT_M, "count": 20},
    ]
    out = build_stats(
        {**COUNTS, "extracted": 220}, rows, HEALTH,
        current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW,
    )["extraction"]
    assert out["stale"] == 200
    assert [v["current"] for v in out["by_prompt_version"]] == [False, True]


def test_each_row_reports_the_model_it_was_extracted_with():
    models = [v["model"] for v in _build()["extraction"]["by_prompt_version"]]
    assert models == ["google/gemini-2.5-flash", CURRENT_M]


def test_nothing_is_stale_when_every_row_is_current():
    out = build_stats(
        COUNTS, [{"version": CURRENT_V, "model": CURRENT_M, "count": 1_200}], HEALTH,
        current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW,
    )
    assert out["extraction"]["stale"] == 0
    assert out["extraction"]["stale_pct"] == 0.0


def test_unextracted_corpus_reports_no_stale_percentage():
    out = build_stats(
        {**COUNTS, "extracted": 0}, [], HEALTH,
        current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW,
    )
    assert out["extraction"]["stale"] == 0
    assert out["extraction"]["stale_pct"] is None


# --- why extraction attempts ended -----------------------------------------


def test_every_bucket_is_reported_even_at_zero():
    """Same rule as the stages dict: an absent key reads as "none of those",
    and "no failures" is precisely the reading that must never be accidental."""
    attempts = _build()["extraction"]["attempts"]
    assert set(attempts) == {
        "ok", "no_html", "no_text", "error", "transient", "unknown", "other",
    }
    assert attempts["no_html"] == 0
    assert attempts["ok"] == 1_050


def test_failed_is_everything_that_is_not_ok():
    out = _build()["extraction"]
    assert out["attempted"] == 1_200
    assert out["failed"] == 150
    assert out["failed_pct"] == pytest.approx(12.5, abs=0.05)


def test_attempts_reconcile_with_the_headline_extracted_count():
    """`churches.extracted` counts `extracted_at IS NOT NULL`, which failures
    stamp too — so the headline has always included churches where nothing was
    extracted. The buckets have to add up to it, or one of the two is lying."""
    out = _build()
    assert out["extraction"]["attempted"] == out["churches"]["extracted"]


def test_no_html_is_reported_apart_from_no_text():
    """The distinction the backfill turns on: `no_html` means R2 has nothing
    behind the artifact and the church needs re-fetching; `no_text` means the
    page was read and was empty. Bucketing them together is what made run
    577's 41 failures unreadable."""
    rows = [
        {"status": "ok", "count": 34},
        {"status": "no_html", "count": 39},
        {"status": "no_text", "count": 2},
    ]
    out = build_stats(COUNTS, BY_VERSION, HEALTH, by_status=rows,
                      stale_counts=STALE_COUNTS,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["extraction"]["attempts"]["no_html"] == 39
    assert out["extraction"]["attempts"]["no_text"] == 2


def test_unrecognized_status_strings_land_in_other():
    """`other` is non-zero only when a code change added a status without
    adding it here — a signal about this file, not about the pipeline."""
    out = build_stats(COUNTS, BY_VERSION, HEALTH,
                      by_status=[{"status": "other", "count": 7}],
                      stale_counts=STALE_COUNTS,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["extraction"]["attempts"]["other"] == 7


def test_awaiting_queue_is_reported_next_to_stale():
    """The runbook says "repeat until awaiting_queue is zero", and reading it
    used to need the crawl token. Watching it against `stale` is what tells a
    draining backfill from one that has failed to a halt."""
    out = _build()["extraction"]
    assert out["stale"] == 1_180
    assert out["awaiting_queue"] == 300


def test_no_extraction_data_reports_zeros_not_a_missing_section():
    out = build_stats(COUNTS, BY_VERSION, HEALTH,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["extraction"]["attempted"] == 0
    assert out["extraction"]["failed_pct"] is None
    assert out["extraction"]["awaiting_queue"] is None


# --- crawl health ----------------------------------------------------------


def test_last_success_is_iso_per_stage():
    last = _build()["crawl"]["last_success"]
    assert last["fetch"] == "2026-07-24T09:17:00+00:00"
    assert last["extract"] == "2026-07-24T06:37:00+00:00"


def test_stage_that_never_succeeded_is_null_not_missing():
    """A stage with no successful run must still appear — an absent key
    reads as "fine", which is the failure mode this endpoint exists for.

    `tag` is deliberately missing from HEALTH, because that is what the
    query returns for a stage that has never finished 'ok'.
    """
    last = _build()["crawl"]["last_success"]
    assert "tag" in last
    assert last["tag"] is None


def test_every_stage_is_reported_even_with_no_runs_at_all():
    out = build_stats(COUNTS, BY_VERSION, {"last_success": [], "window": [], "window_days": 7},
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["crawl"]["last_success"] == {"fetch": None, "extract": None, "tag": None}


def test_run_window_defaults_absent_statuses_to_zero():
    runs = _build()["crawl"]["runs"]
    assert runs == {"window_days": 7, "ok": 39, "error": 1, "partial": 0, "running": 0}


# --- staleness: the signal an absent row cannot fake -----------------------


def test_recent_success_is_not_stale():
    stages = _build()["crawl"]["stages"]
    # fetch made progress 2h43m before NOW, well inside its 12h budget
    assert stages["fetch"]["age_seconds"] == 2 * 3600 + 43 * 60
    assert stages["fetch"]["stale"] is False


def test_stage_past_its_budget_is_stale():
    """A stage that dies before writing its crawl_runs row contributes no
    error, so `runs.error` stays 0 while nothing succeeds. Age since the last
    success is what catches that — exactly the 2026-07-27 failure, where the
    connection died before start_run and /status saw a clean pipeline."""
    # NOW is 2026-07-24 12:00Z; fetch last made progress 13h before that,
    # one hour past its 12h budget.
    stopped = datetime(2026, 7, 23, 23, 0, tzinfo=timezone.utc)
    late = {
        "last_success": [
            {"stage": "fetch", "last_success": stopped, "last_progress": stopped},
            {"stage": "extract",
             "last_success": datetime(2026, 7, 24, 6, 37, tzinfo=timezone.utc),
             "last_progress": datetime(2026, 7, 24, 6, 37, tzinfo=timezone.utc)},
            {"stage": "tag",
             "last_success": datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc),
             "last_progress": datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc)},
        ],
        "window": [{"status": "ok", "count": 39}],   # no errors at all
        "window_days": 7,
    }
    out = build_stats(COUNTS, BY_VERSION, late,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["crawl"]["runs"]["error"] == 0        # nothing recorded a failure
    assert out["crawl"]["stages"]["fetch"]["age_seconds"] == 13 * 3600
    assert out["crawl"]["stages"]["fetch"]["stale"] is True
    assert out["crawl"]["pipeline_ok"] is False      # and it still reports unhealthy


def test_one_missed_fetch_run_does_not_trip_the_pipeline():
    """The 2026-07-27 false alarm. fetch runs every 4h; at an 8h budget a
    single failure guaranteed a red pipeline, because the retry is 4h out and
    age crosses 8h before recovery is even possible. One miss has to be
    survivable or the signal is noise."""
    missed = {
        "last_success": [
            # succeeded 9h ago: one run missed, the next is due in ~3h
            {"stage": s,
             "last_success": datetime(2026, 7, 24, 3, 0, tzinfo=timezone.utc),
             "last_progress": datetime(2026, 7, 24, 3, 0, tzinfo=timezone.utc)}
            for s in ("fetch", "extract", "tag")
        ],
        "window": [{"status": "ok", "count": 39}],
        "window_days": 7,
    }
    out = build_stats(COUNTS, BY_VERSION, missed,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["crawl"]["stages"]["fetch"]["stale"] is False
    assert out["crawl"]["pipeline_ok"] is True


# --- liveness vs perfection ------------------------------------------------


def test_a_stage_that_only_ever_runs_partial_is_still_alive():
    """The reason staleness moved off `last_success`. A batch with one bad row
    is 'partial', so during a backfill with a real error rate the last flawless
    run recedes forever — /api/stats reported extract 21h stale on 2026-07-27
    while it was processing churches on schedule. Progress, not perfection, is
    what says the pipeline is up."""
    backfilling = {
        "last_success": [
            # last clean run was 3 days ago; every run since got rows through
            {"stage": "extract",
             "last_success": datetime(2026, 7, 21, 6, 0, tzinfo=timezone.utc),
             "last_progress": datetime(2026, 7, 24, 10, 37, tzinfo=timezone.utc)},
            {"stage": "fetch",
             "last_success": datetime(2026, 7, 24, 9, 17, tzinfo=timezone.utc),
             "last_progress": datetime(2026, 7, 24, 9, 17, tzinfo=timezone.utc)},
            {"stage": "tag",
             "last_success": datetime(2026, 7, 24, 7, 47, tzinfo=timezone.utc),
             "last_progress": datetime(2026, 7, 24, 7, 47, tzinfo=timezone.utc)},
        ],
        "window": [{"status": "partial", "count": 12}],
        "window_days": 7,
    }
    out = build_stats(COUNTS, BY_VERSION, backfilling,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    extract = out["crawl"]["stages"]["extract"]
    assert extract["age_seconds"] == 83 * 60          # measured from last_progress
    assert extract["stale"] is False
    assert out["crawl"]["pipeline_ok"] is True
    # ...and the strict signal is still reported, just not alerted on.
    assert extract["last_success"] == "2026-07-21T06:00:00+00:00"
    assert extract["last_progress"] == "2026-07-24T10:37:00+00:00"


def test_a_stage_making_no_progress_is_stale_even_if_it_keeps_running():
    """The other half: `last_progress` requires rows_ok > 0 (enforced in SQL),
    so a stage whose every row fails reports no progress at all and goes
    stale. Otherwise "runs constantly, achieves nothing" would read as green."""
    grinding = {
        "last_success": [
            {"stage": s,
             "last_success": None,
             "last_progress": None}
            for s in ("fetch", "extract", "tag")
        ],
        "window": [{"status": "partial", "count": 40}],
        "window_days": 7,
    }
    out = build_stats(COUNTS, BY_VERSION, grinding,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["crawl"]["stages"]["extract"]["stale"] is True
    assert out["crawl"]["pipeline_ok"] is False


def test_never_succeeded_counts_as_stale_not_unknown():
    out = build_stats(COUNTS, BY_VERSION, {"last_success": [], "window": [], "window_days": 7},
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    for stage in ("fetch", "extract", "tag"):
        assert out["crawl"]["stages"][stage]["age_seconds"] is None
        assert out["crawl"]["stages"][stage]["stale"] is True
    assert out["crawl"]["pipeline_ok"] is False


def test_pipeline_ok_needs_every_stage_fresh():
    fresh = {
        "last_success": [
            {"stage": s,
             "last_success": datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc),
             "last_progress": datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc)}
            for s in ("fetch", "extract", "tag")
        ],
        "window": [{"status": "ok", "count": 3}],
        "window_days": 7,
    }
    out = build_stats(COUNTS, BY_VERSION, fresh,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["crawl"]["pipeline_ok"] is True


def test_stage_budgets_survive_one_missed_run():
    """A budget has to clear cadence x2 or a single failure alerts on its own,
    because the retry only comes one cadence later. fetch at 8h against a 4h
    cron failed this and cried wolf on 2026-07-27."""
    stages = _build()["crawl"]["stages"]
    # After one miss the next success lands at 2 x cadence, so the budget has
    # to reach that. Equality is the boundary and passes, since `stale` is
    # `age > budget`.
    for stage, cadence_s in (("fetch", 4 * 3600), ("extract", 8 * 3600), ("tag", 24 * 3600)):
        assert stages[stage]["max_age_seconds"] >= 2 * cadence_s, stage


# --- caching ---------------------------------------------------------------


def test_endpoint_serves_from_cache_within_ttl(monkeypatch):
    """The queries are full scans of a 134k-row table on a public route, so
    a second request inside the TTL must not touch the database at all."""
    import asyncio

    from backend.routers import stats as stats_mod

    hits = {"n": 0}

    class FakeRepo:
        def __init__(self, con):
            pass

        async def church_counts(self):
            hits["n"] += 1
            return COUNTS

        async def extraction_by_prompt_version(self):
            return BY_VERSION

        async def extraction_status_breakdown(self):
            return BY_STATUS

        async def crawl_health(self):
            return HEALTH

    class FakeCrawlRepo:
        def __init__(self, con):
            pass

        async def count_stale_extractions(self, version, model):
            return STALE_COUNTS

    class FakeAcquire:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(stats_mod, "StatsRepository", FakeRepo)
    monkeypatch.setattr(stats_mod, "CrawlRepository", FakeCrawlRepo)
    monkeypatch.setattr(stats_mod.pool, "acquire", lambda: FakeAcquire())
    monkeypatch.setattr(stats_mod, "_cache", {"at": 0.0, "value": None})

    first = asyncio.run(stats_mod.stats())
    second = asyncio.run(stats_mod.stats())

    assert hits["n"] == 1
    assert first == second
    assert first["cache_ttl_seconds"] == stats_mod.CACHE_TTL_S


def test_endpoint_requeries_once_the_ttl_lapses(monkeypatch):
    import asyncio

    from backend.routers import stats as stats_mod

    hits = {"n": 0}

    class FakeRepo:
        def __init__(self, con):
            pass

        async def church_counts(self):
            hits["n"] += 1
            return COUNTS

        async def extraction_by_prompt_version(self):
            return BY_VERSION

        async def extraction_status_breakdown(self):
            return BY_STATUS

        async def crawl_health(self):
            return HEALTH

    class FakeCrawlRepo:
        def __init__(self, con):
            pass

        async def count_stale_extractions(self, version, model):
            return STALE_COUNTS

    class FakeAcquire:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(stats_mod, "StatsRepository", FakeRepo)
    monkeypatch.setattr(stats_mod, "CrawlRepository", FakeCrawlRepo)
    monkeypatch.setattr(stats_mod.pool, "acquire", lambda: FakeAcquire())
    monkeypatch.setattr(stats_mod, "_cache", {"at": 0.0, "value": None})

    asyncio.run(stats_mod.stats())
    # pretend the cached entry is older than the TTL
    stats_mod._cache["at"] -= stats_mod.CACHE_TTL_S + 1
    asyncio.run(stats_mod.stats())

    assert hits["n"] == 2


# --- no per-church detail leaks -------------------------------------------


def test_response_is_aggregate_only():
    """The endpoint is unauthenticated; it must never carry church detail.
    Every leaf has to be a number, a string, a bool or None."""
    def leaves(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from leaves(v)
        elif isinstance(node, list):
            for v in node:
                yield from leaves(v)
        else:
            yield node

    for leaf in leaves(_build()):
        assert leaf is None or isinstance(leaf, (int, float, str, bool))
