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
HEALTH = {
    "last_success": [
        {"stage": "fetch", "last_success": datetime(2026, 7, 24, 9, 17, tzinfo=timezone.utc)},
        {"stage": "extract", "last_success": datetime(2026, 7, 24, 6, 37, tzinfo=timezone.utc)},
    ],
    "window": [{"status": "ok", "count": 39}, {"status": "error", "count": 1}],
    "window_days": 7,
}


def _build(**kw):
    kw.setdefault("current_prompt_version", CURRENT_V)
    kw.setdefault("current_model", CURRENT_M)
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
    # fetch succeeded 2h43m before NOW, well inside its 8h budget
    assert stages["fetch"]["age_seconds"] == 2 * 3600 + 43 * 60
    assert stages["fetch"]["stale"] is False


def test_stage_past_its_budget_is_stale():
    """A stage that dies before writing its crawl_runs row contributes no
    error, so `runs.error` stays 0 while nothing succeeds. Age since the last
    success is what catches that — exactly the 2026-07-27 failure, where the
    connection died before start_run and /status saw a clean pipeline."""
    late = {
        "last_success": [
            # fetch last succeeded 9h ago, budget is 8h
            {"stage": "fetch", "last_success": datetime(2026, 7, 24, 3, 0, tzinfo=timezone.utc)},
            {"stage": "extract", "last_success": datetime(2026, 7, 24, 6, 37, tzinfo=timezone.utc)},
            {"stage": "tag", "last_success": datetime(2026, 7, 24, 1, 0, tzinfo=timezone.utc)},
        ],
        "window": [{"status": "ok", "count": 39}],   # no errors at all
        "window_days": 7,
    }
    out = build_stats(COUNTS, BY_VERSION, late,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["crawl"]["runs"]["error"] == 0        # nothing recorded a failure
    assert out["crawl"]["stages"]["fetch"]["stale"] is True
    assert out["crawl"]["pipeline_ok"] is False      # and it still reports unhealthy


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
            {"stage": s, "last_success": datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc)}
            for s in ("fetch", "extract", "tag")
        ],
        "window": [{"status": "ok", "count": 3}],
        "window_days": 7,
    }
    out = build_stats(COUNTS, BY_VERSION, fresh,
                      current_prompt_version=CURRENT_V, current_model=CURRENT_M, now=NOW)
    assert out["crawl"]["pipeline_ok"] is True


def test_stage_budgets_are_looser_than_the_cron_cadence():
    """Doubled-ish, so one missed run plus GitHub's scheduling drift doesn't
    cry wolf. A budget tighter than the cadence would alert constantly."""
    stages = _build()["crawl"]["stages"]
    assert stages["fetch"]["max_age_seconds"] > 4 * 3600     # cron: every 4h
    assert stages["extract"]["max_age_seconds"] > 12 * 3600  # cron: twice daily
    assert stages["tag"]["max_age_seconds"] > 24 * 3600      # cron: daily


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

        async def crawl_health(self):
            return HEALTH

    class FakeAcquire:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(stats_mod, "StatsRepository", FakeRepo)
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

        async def crawl_health(self):
            return HEALTH

    class FakeAcquire:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(stats_mod, "StatsRepository", FakeRepo)
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
