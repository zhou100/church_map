"""analytics/scripts/build_seeds.py: audit grading and stale re-check verdicts (no network)."""
import csv
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "analytics" / "scripts" / "build_seeds.py"
_spec = importlib.util.spec_from_file_location("build_seeds", _PATH)
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)


# --- Review of PR #41, issue 3: grading must compare complete values ---------------

@pytest.mark.parametrize("auditor,muse,expected", [
    ("9 AM", "Sunday worship 9 PM", "disagree"),
    ("10 AM", "Sunday 10:30 AM", "disagree"),
    ("Sun 10:00am? English", "Every Sunday at 10 am Pacific", "agree"),
    ("Sundays at 10:15 a.m.", "8:00 a.m. North Campus | 10:15 a.m. South Campus", "agree"),
    ("Sun 10:00", "Sunday 10:00 am", "needs_review"),
    ("N/A", "Sunday 10 am", "needs_review"),
])
def test_grade_service_times(auditor, muse, expected):
    assert bs.grade_service_times(auditor, muse) == expected


@pytest.mark.parametrize("auditor,muse,expected", [
    ("123 Main St", "123 Oak St", "disagree"),
    ("123 Main St, Los Altos, CA 94022", "123 Main Street, Los Altos 94024", "disagree"),
    ("1600 Santa Lucia Ave.\n San Bruno, CA 94066", "1600 Santa Lucia Avenue, San Bruno 94066", "agree"),
    ("ST. AMBROSE EPISCOPAL CHURCH\n900 Edgewater Blvd.\nFoster City, CA 94404-3709",
     "900 Edgewater Blvd, Foster City 94404", "agree"),
    ("600 W. 42nd Avenue", "600 West 42nd Ave, San Mateo 94403", "agree"),
    ("Edgewater Blvd", "900 Edgewater Blvd", "needs_review"),
])
def test_grade_street(auditor, muse, expected):
    assert bs.grade_street(auditor, muse) == expected


def test_grade_phone():
    assert bs.grade_phone("6503493544", "(650) 349-3544") == "agree"
    assert bs.grade_phone("6503493544", "(650) 349-3545") == "disagree"
    assert bs.grade_phone("349-3544", "(650) 349-3544") == "needs_review"


# --- Review of PR #41, issue 2: a verdict is bound to the exact fact it checked ----

RESULT_COLS = ["church_id", "status", "street_address", "city", "zip", "address_source_url",
               "address_source_type", "address_excerpt", "notes", "checked_at"]


def _write(path, cols, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _checks_after(tmp_path, monkeypatch, row_at_check, row_published):
    ret, seeds = tmp_path / "returns", tmp_path / "seeds"
    (ret / "recheck").mkdir(parents=True)
    seeds.mkdir()
    monkeypatch.setattr(bs, "RET", ret)
    monkeypatch.setattr(bs, "SEEDS", seeds)
    _write(ret / "results_current.csv", RESULT_COLS, [row_published])
    _write(ret / "recheck" / "results_current.csv",
           ["row_key", "group", "verdict", "http_status", "match_mode", "checked_at", "fact_fingerprint"],
           [{"row_key": "1", "group": "address", "verdict": "verified", "http_status": "200",
             "match_mode": "exact", "checked_at": "2026-10-20T00:00:00Z",
             "fact_fingerprint": bs.fact_fingerprint(row_at_check, "address")}])
    files, fps = bs.build_results({"1": "A_calibration"})
    bs.build_source_checks(files, {}, fps)
    return list(csv.DictReader((seeds / "source_checks.csv").open(encoding="utf-8")))


BASE = {"church_id": "1", "status": "active", "street_address": "100 Main St", "city": "San Mateo",
        "zip": "94401", "address_source_url": "https://church.example.org/contact",
        "address_source_type": "own_site", "address_excerpt": "100 Main St, San Mateo", "notes": "",
        "checked_at": "2026-10-20T00:00:00Z"}


def test_unchanged_fact_keeps_its_verdict(tmp_path, monkeypatch):
    assert _checks_after(tmp_path, monkeypatch, BASE, BASE)[0]["verdict"] == "verified"


@pytest.mark.parametrize("change", [
    {"street_address": "200 Main St"},
    {"address_source_url": "https://other.example.org/"},
    {"address_excerpt": "200 Main St, San Mateo"},
])
def test_changed_fact_makes_old_verdict_stale(tmp_path, monkeypatch, change):
    rows = _checks_after(tmp_path, monkeypatch, BASE, {**BASE, **change})
    assert rows[0]["verdict"] == "stale"


def test_check_without_fingerprint_is_stale(tmp_path, monkeypatch):
    ret = tmp_path / "returns"
    rows = _checks_after(tmp_path, monkeypatch, BASE, BASE)
    path = ret / "recheck" / "results_current.csv"
    data = list(csv.DictReader(path.open(encoding="utf-8")))
    for d in data:
        d.pop("fact_fingerprint")
    _write(path, ["row_key", "group", "verdict", "http_status", "match_mode", "checked_at"], data)
    files, fps = bs.build_results({"1": "A_calibration"})
    bs.build_source_checks(files, {}, fps)
    rows = list(csv.DictReader((tmp_path / "seeds" / "source_checks.csv").open(encoding="utf-8")))
    assert rows[0]["verdict"] == "stale"


# --- Round 4 intake ------------------------------------------------------------

def test_service_times_without_a_time_in_the_excerpt_are_not_published():
    r = bs.sanitize({"service_times_verbatim": "Sunday 10:00 am", "service_languages": "English",
                     "service_excerpt": "English is our common language", "checked_at": ""})
    assert r["service_times_verbatim"] == "" and r["service_times_unsupported"] == "true"
    assert r["service_languages"] == "English"


def test_korean_time_in_excerpt_supports_the_times():
    r = bs.sanitize({"service_times_verbatim": "주일 예배 11:00 AM",
                     "service_excerpt": "우리교회의 주일 예배시간은 주일 오전 11시 입니다.", "checked_at": ""})
    assert r["service_times_verbatim"] and r["service_times_unsupported"] == "false"


@pytest.mark.parametrize("stamp,reliable", [
    ("2026-10-20T16:41:00Z", "true"),
    ("2026-10-20T16:508Z", "false"),      # malformed (task D)
    ("2026-10-20T17:59:00Z", "false"),    # after the file was received
])
def test_checked_at_reliability(stamp, reliable):
    r = bs.sanitize({"checked_at": stamp}, "results_D.csv")
    assert r["checked_at_reliable"] == reliable
