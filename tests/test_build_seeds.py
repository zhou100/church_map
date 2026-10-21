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
def test_checked_at_reliability(stamp, reliable, monkeypatch):
    # Pin the receipt time: the real registry changes as returns are re-delivered.
    monkeypatch.setitem(bs.RECEIVED_AT, "results_D.csv", "2026-10-20T17:31:34Z")
    r = bs.sanitize({"checked_at": stamp}, "results_D.csv")
    assert r["checked_at_reliable"] == reliable


def test_stamp_shared_by_many_rows_is_unreliable():
    rows = [{"checked_at": "2026-10-19T23:39:05Z"}] * 11 + [{"checked_at": "2026-10-19T21:30:00Z"}]
    bulk = frozenset(bs.bulk_stamps(rows))
    assert bs.sanitize(dict(rows[0]), "", bulk)["checked_at_reliable"] == "false"
    assert bs.sanitize(dict(rows[-1]), "", bulk)["checked_at_reliable"] == "true"


def test_build_reviews_runs_and_grades(tmp_path, monkeypatch):
    """Regression: build_reviews referenced a constant that had been deleted; nothing ran it."""
    ret, seeds = tmp_path / "returns", tmp_path / "seeds"
    ret.mkdir()
    seeds.mkdir()
    monkeypatch.setattr(bs, "RET", ret)
    monkeypatch.setattr(bs, "SEEDS", seeds)
    _write(ret / "audit_key.csv", ["review_id", "church_id", "field", "muse_value"], [
        {"review_id": "R1", "church_id": "1", "field": "service_times", "muse_value": "Sunday 9 PM"},
        {"review_id": "R2", "church_id": "76692", "field": "status", "muse_value": "active"},
        {"review_id": "R3", "church_id": "1", "field": "street_address", "muse_value": "100 Main St, San Mateo 94401"},
    ])
    _write(ret / "audit_worksheet.csv", ["church_id", "stratum", "field", "your_answer", "evidence_url"], [
        {"church_id": "1", "stratum": "s", "field": "service_times", "your_answer": "Sun 9 AM", "evidence_url": ""},
        {"church_id": "76692", "stratum": "s", "field": "status", "your_answer": "closed", "evidence_url": ""},
        {"church_id": "1", "stratum": "s", "field": "street_address", "your_answer": "100 Main Street", "evidence_url": ""},
    ])
    bs.build_reviews()
    got = {r["review_id"]: r["verdict"] for r in csv.DictReader((seeds / "quality_reviews.csv").open(encoding="utf-8"))}
    assert got == {"1-service_times": "disagree", "76692-status": "definition_disagreement",
                   "1-street_address": "agree"}


def test_address_not_stated_by_its_excerpt_is_not_published():
    r = bs.sanitize({"street_address": "107 San Pedro Road",
                     "address_excerpt": "Parish office: 107 San Mateo Avenue, San Bruno", "checked_at": ""})
    assert r["street_address"] == "" and r["address_unsupported"] == "true"
    r = bs.sanitize({"street_address": "107 San Pedro Rd",
                     "address_excerpt": "107 San Pedro Road Colma, CA 94014", "checked_at": ""})
    assert r["street_address"] == "107 San Pedro Rd" and r["address_unsupported"] == "false"


def test_service_times_not_matching_their_excerpt_are_withheld():
    r = bs.sanitize({"service_times_verbatim": "Sunday worship 10 AM",
                     "service_excerpt": "Saturday Bible study 10 AM; Sunday worship 11 AM", "checked_at": ""})
    assert r["service_times_verbatim"] == "" and r["service_times_unsupported"] == "true"


def test_boolean_worship_location_values_are_normalized():
    assert bs.sanitize({"address_is_worship_location": "True", "checked_at": ""})["address_is_worship_location"] == "yes"
    assert bs.sanitize({"address_is_worship_location": "False", "checked_at": ""})["address_is_worship_location"] == "no"


# --- Carry-over of a recent 'verified' through a transient fetch failure ---------------

HIST = {("1", "address", "fpA"): [("2026-10-20T16:00:00Z", "verified")]}


@pytest.mark.parametrize("verdict,status,checked_at,key,expected", [
    ("fetch_failed", "503", "2026-10-21T10:00:00Z", ("1", "address", "fpA"), ("verified", "2026-10-20T16:00:00Z", True)),
    ("fetch_failed", "", "2026-10-21T10:00:00Z", ("1", "address", "fpA"), ("verified", "2026-10-20T16:00:00Z", True)),   # timeout
    ("fetch_failed", "503", "2026-12-01T10:00:00Z", ("1", "address", "fpA"), ("fetch_failed", "2026-12-01T10:00:00Z", False)),  # too old
    ("fetch_failed", "503", "2026-10-21T10:00:00Z", ("1", "address", "fpB"), ("fetch_failed", "2026-10-21T10:00:00Z", False)),  # fact changed
    ("fetch_failed", "403", "2026-10-21T10:00:00Z", ("1", "address", "fpA"), ("fetch_failed", "2026-10-21T10:00:00Z", False)),  # not transient
    ("source_gone", "404", "2026-10-21T10:00:00Z", ("1", "address", "fpA"), ("source_gone", "2026-10-21T10:00:00Z", False)),   # page deleted
    ("not_found", "200", "2026-10-21T10:00:00Z", ("1", "address", "fpA"), ("not_found", "2026-10-21T10:00:00Z", False)),
    ("robots_blocked", "", "2026-10-21T10:00:00Z", ("1", "address", "fpA"), ("robots_blocked", "2026-10-21T10:00:00Z", False)),
])
def test_carry_over(verdict, status, checked_at, key, expected):
    assert bs.carry_over(verdict, status, checked_at, key, HIST) == expected


def test_a_later_negative_verdict_cancels_an_earlier_verification():
    """Review of 91be6af: verified -> not_found -> fetch_failed must stay unverified."""
    hist = {("1", "address", "fpA"): [("2026-10-20T10:00:00Z", "verified"), ("2026-10-20T12:00:00Z", "not_found"),
                                      ("2026-10-20T14:00:00Z", "fetch_failed")]}
    assert bs.carry_over("fetch_failed", "503", "2026-10-21T10:00:00Z", ("1", "address", "fpA"), hist)[2] is False
    hist[("1", "address", "fpA")].append(("2026-10-20T16:00:00Z", "verified"))  # verified again later
    assert bs.carry_over("fetch_failed", "503", "2026-10-21T10:00:00Z", ("1", "address", "fpA"), hist)[2] is True


def test_carry_over_end_to_end(tmp_path, monkeypatch):
    rows = _checks_after(tmp_path, monkeypatch, BASE, BASE)  # writes a verified check
    ret = tmp_path / "returns"
    fp = bs.fact_fingerprint(BASE, "address")
    hist = ret / "recheck" / "history"
    hist.mkdir(parents=True)
    _write(hist / "results_current.csv", ["row_key", "group", "verdict", "fact_fingerprint", "checked_at"],
           [{"row_key": "1", "group": "address", "verdict": "verified", "fact_fingerprint": fp,
             "checked_at": "2026-10-20T00:00:00Z"}])
    _write(ret / "recheck" / "results_current.csv",
           ["row_key", "group", "verdict", "http_status", "match_mode", "checked_at", "fact_fingerprint"],
           [{"row_key": "1", "group": "address", "verdict": "fetch_failed", "http_status": "503", "match_mode": "",
             "checked_at": "2026-10-22T00:00:00Z", "fact_fingerprint": fp}])
    files, fps = bs.build_results({"1": "A_calibration"})
    bs.build_source_checks(files, {}, fps)
    out = list(csv.DictReader((tmp_path / "seeds" / "source_checks.csv").open(encoding="utf-8")))[0]
    assert (out["verdict"], out["carried_over"], out["checked_at"]) == ("verified", "true", "2026-10-20T00:00:00Z")


# --- Round 6 overlays (task S service times, task W worship location) -------------------

def _overlay_env(tmp_path, monkeypatch, base, s_row=None, w_row=None, w_verdict="verified", s_verdict="verified",
                 w_asked=None):
    ret, seeds, handoff = tmp_path / "returns", tmp_path / "seeds", tmp_path / "handoff"
    (ret / "recheck").mkdir(parents=True)
    (handoff / "outbox").mkdir(parents=True)
    seeds.mkdir()
    monkeypatch.setattr(bs, "RET", ret)
    monkeypatch.setattr(bs, "SEEDS", seeds)
    monkeypatch.setattr(bs, "HANDOFF", handoff)
    monkeypatch.setattr(bs, "STALE_W", set())
    if w_row and w_asked is not False:  # the W question was about this address (default: the base record's)
        asked = w_asked or base
        _write(handoff / "outbox" / "worship_location_W_input.csv", ["subject_type", "subject_id", "city", "street_address"],
               [dict(subject_type=w_row["subject_type"], subject_id=w_row["subject_id"], city=asked.get("city", ""),
                     street_address=asked.get("street_address", ""))])
    cols = sorted(set(base) | {"service_times_verbatim", "service_languages", "service_source_url",
                               "service_source_type", "service_excerpt", "address_is_worship_location"})
    _write(ret / "results_current.csv", cols, [base])
    rc = ["row_key", "group", "verdict", "http_status", "match_mode", "checked_at", "fact_fingerprint"]
    if s_row:
        _write(ret / "service_fixes_S.csv", list(s_row), [s_row])
        _write(ret / "recheck" / "service_fixes_S.csv", rc, [dict(row_key=s_row["subject_id"], group="service",
               verdict=s_verdict, http_status="200", match_mode="exact", checked_at="2026-10-21T18:00:00Z",
               fact_fingerprint=bs.fact_fingerprint(s_row, "service"))])
    if w_row:
        _write(ret / "worship_location_W.csv", list(w_row), [w_row])
        _write(ret / "recheck" / "worship_location_W.csv", rc, [dict(row_key=w_row["subject_id"], group="worship",
               verdict=w_verdict, http_status="200", match_mode="exact", checked_at="2026-10-21T18:00:00Z",
               fact_fingerprint=bs.fact_fingerprint(w_row, "worship"))])
    overlays, used = bs.load_overlays(), {}
    files, fps = bs.build_results({"1": "A_calibration"}, overlays, used)
    bs.build_source_checks(files, {}, fps, used)
    res = list(csv.DictReader((seeds / "muse_results.csv").open(encoding="utf-8")))[0]
    checks = {r["fact_group"]: r["verdict"] for r in csv.DictReader((seeds / "source_checks.csv").open(encoding="utf-8"))}
    return res, checks


S_ROW = {"subject_type": "church", "subject_id": "1", "service_times_verbatim": "Sunday Worship 10:00 AM",
         "service_languages": "English", "service_source_url": "https://church.example.org/visit",
         "service_source_type": "own_site", "service_excerpt": "Sunday Worship 10:00 AM in the sanctuary",
         "checked_at": "2026-10-21T18:00:00Z", "notes": ""}


def test_service_answer_replaces_the_schedule_and_is_checked_on_its_own_page(tmp_path, monkeypatch):
    base = {**BASE, "service_times_verbatim": "Sat 5 pm; Sun 8, 10, 12; daily 8 am", "service_excerpt": "Sunday 10 am"}
    res, checks = _overlay_env(tmp_path, monkeypatch, base, s_row=S_ROW)
    assert res["service_times_verbatim"] == "Sunday Worship 10:00 AM" and checks["service"] == "verified"


def test_service_answer_that_failed_its_check_is_not_verified(tmp_path, monkeypatch):
    res, checks = _overlay_env(tmp_path, monkeypatch, dict(BASE), s_row=S_ROW, s_verdict="not_found")
    assert checks["service"] == "not_found"


W_ROW = {"subject_type": "church", "subject_id": "1", "address_is_worship_location": "yes",
         "worship_street_address": "", "worship_city": "", "worship_zip": "",
         "source_url": "https://church.example.org/visit", "source_type": "own_site",
         "excerpt": "Join us Sundays at 100 Main St", "checked_at": "2026-10-21T18:00:00Z", "notes": ""}


def test_worship_answer_counts_only_if_its_excerpt_verified(tmp_path, monkeypatch):
    base = {**BASE, "address_is_worship_location": "unknown"}
    res, _ = _overlay_env(tmp_path, monkeypatch, base, w_row=W_ROW)
    assert res["address_is_worship_location"] == "yes"
    res, _ = _overlay_env(tmp_path / "b", monkeypatch, base, w_row=W_ROW, w_verdict="not_found")
    assert res["address_is_worship_location"] == "unknown"


def test_corrected_street_replaces_the_address_and_takes_its_check_from_w(tmp_path, monkeypatch):
    base = {**BASE, "street_address": "100 Main Ave", "address_excerpt": "100 Main Ave"}
    w = {**W_ROW, "worship_street_address": "100 Main Street", "worship_city": "San Mateo", "worship_zip": "94401",
         "excerpt": "Our church: 100 Main Street, San Mateo"}
    res, checks = _overlay_env(tmp_path, monkeypatch, base, w_row=w)
    assert res["street_address"] == "100 Main Street" and res["address_unsupported"] == "false"
    assert checks["address"] == "verified"


def test_no_for_the_old_address_does_not_follow_the_worship_address_that_replaces_it(tmp_path, monkeypatch):
    # Review of 69293de: W answers "no" (they don't meet at the recorded office) and gives
    # the worship address; the replacement address is where they meet.
    base = {**BASE, "street_address": "9 Office Park", "address_excerpt": "9 Office Park",
            "address_is_worship_location": "unknown"}
    w = {**W_ROW, "address_is_worship_location": "no", "worship_street_address": "100 Main Street",
         "worship_city": "San Mateo", "worship_zip": "94401", "excerpt": "Worship with us Sundays at 100 Main Street"}
    res, _ = _overlay_env(tmp_path, monkeypatch, base, w_row=w)
    assert res["street_address"] == "100 Main Street" and res["address_is_worship_location"] == "yes"
    # Without a replacement address, "no" stays on the recorded one.
    res, _ = _overlay_env(tmp_path / "b", monkeypatch, base, w_row={**W_ROW, "address_is_worship_location": "no"})
    assert res["address_is_worship_location"] == "no"


def test_worship_answer_is_bound_to_the_address_it_was_asked_about(tmp_path, monkeypatch):
    # Review of b8898c8: a "yes" for 100 Main Street must not carry over to 200 Main Street.
    asked = {**BASE, "street_address": "100 Main Street", "address_is_worship_location": "unknown"}
    res, _ = _overlay_env(tmp_path, monkeypatch, asked, w_row=W_ROW)
    assert res["address_is_worship_location"] == "yes"
    moved = {**asked, "street_address": "200 Main Street", "address_excerpt": "200 Main Street"}
    res, _ = _overlay_env(tmp_path / "b", monkeypatch, moved, w_row=W_ROW, w_asked=asked)
    assert res["address_is_worship_location"] == "unknown" and bs.STALE_W == {("church", "1")}
    # Case and spacing don't make it a different address.
    same = {**asked, "street_address": "100  MAIN street"}
    res, _ = _overlay_env(tmp_path / "c", monkeypatch, same, w_row=W_ROW, w_asked=asked)
    assert res["address_is_worship_location"] == "yes"


def test_worship_answer_without_its_question_is_not_used(tmp_path, monkeypatch):
    base = {**BASE, "address_is_worship_location": "unknown"}
    res, _ = _overlay_env(tmp_path, monkeypatch, base, w_row=W_ROW, w_asked=False)
    assert res["address_is_worship_location"] == "unknown"



def test_a_later_pass_that_moves_the_address_takes_w_ownership_back(tmp_path, monkeypatch):
    # Review of ac909e6: W corrected round 1's 100 Main Ave; a later pass records 200 Main
    # Street and its own check says not_found. The old W "verified" must not follow.
    ret, seeds, handoff = tmp_path / "returns", tmp_path / "seeds", tmp_path / "handoff"
    (ret / "recheck").mkdir(parents=True)
    (handoff / "outbox").mkdir(parents=True)
    seeds.mkdir()
    for name, val in (("RET", ret), ("SEEDS", seeds), ("HANDOFF", handoff), ("STALE_W", set()),
                      ("RESULT_FILES", [("results_current.csv", None), ("results_E.csv", "E")])):
        monkeypatch.setattr(bs, name, val)
    rc = ["row_key", "group", "verdict", "http_status", "match_mode", "checked_at", "fact_fingerprint"]
    old = {**BASE, "street_address": "100 Main Ave", "address_excerpt": "100 Main Ave"}
    new = {**BASE, "street_address": "200 Main Street", "address_excerpt": "200 Main Street"}
    w = {**W_ROW, "address_is_worship_location": "no", "worship_street_address": "100 Main Street",
         "worship_city": "San Mateo", "worship_zip": "94401", "excerpt": "Worship at 100 Main Street, San Mateo"}
    for fname, row, verdict in (("results_current.csv", old, "verified"), ("results_E.csv", new, "not_found")):
        _write(ret / fname, list(row), [row])
        _write(ret / "recheck" / fname, rc, [dict(row_key="1", group="address", verdict=verdict, http_status="200",
               match_mode="exact", checked_at="2026-10-21T18:00:00Z", fact_fingerprint=bs.fact_fingerprint(row, "address"))])
    _write(ret / "worship_location_W.csv", list(w), [w])
    _write(ret / "recheck" / "worship_location_W.csv", rc, [dict(row_key="1", group="worship", verdict="verified",
           http_status="200", match_mode="exact", checked_at="2026-10-21T18:00:00Z",
           fact_fingerprint=bs.fact_fingerprint(w, "worship"))])
    _write(handoff / "outbox" / "worship_location_W_input.csv", ["subject_type", "subject_id", "city", "street_address"],
           [dict(subject_type="church", subject_id="1", city="San Mateo", street_address="100 Main Ave")])
    overlays, used = bs.load_overlays(), {}
    files, fps = bs.build_results({"1": "A_calibration"}, overlays, used)
    bs.build_source_checks(files, {}, fps, used)
    res = list(csv.DictReader((seeds / "muse_results.csv").open(encoding="utf-8")))[0]
    checks = {r["fact_group"]: r["verdict"] for r in csv.DictReader((seeds / "source_checks.csv").open(encoding="utf-8"))}
    assert res["street_address"] == "200 Main Street" and checks["address"] == "not_found"
    assert used == {} and bs.STALE_W == {("church", "1")}


# --- Census geocodes seed --------------------------------------------------------------

def _geocode_env(tmp_path, monkeypatch, receipt_matches=True):
    exports, seeds = tmp_path / "exports", tmp_path / "seeds"
    exports.mkdir()
    seeds.mkdir()
    monkeypatch.setattr(bs, "EXPORTS", exports)
    monkeypatch.setattr(bs, "SEEDS", seeds)
    _write(exports / "geocode_input_old.csv", ["geo_id", "street", "city", "state", "zip"],
           [dict(geo_id="candidate:X-1", street="100 Main St", city="San Mateo", state="CA", zip="94401")])
    _write(exports / "geocode_input.csv", ["geo_id", "street", "city", "state", "zip"],  # regenerated since
           [dict(geo_id="candidate:X-1", street="200 Main St", city="San Mateo", state="CA", zip="94401")])
    _write(exports / "geocode_output.csv", bs.GEOCODE_COLS[:1] + ["status", "latitude", "longitude"],
           [dict(geo_id="candidate:X-1", status="ok", latitude="37.5", longitude="-122.3")])
    old_sha = bs._sha256(exports / "geocode_input_old.csv")
    out_sha = bs._sha256(exports / "geocode_output.csv") if receipt_matches else "0" * 64
    (exports / "geocode_reconciliation.json").write_text(f'{{"input_sha256": "{old_sha}", "output_sha256": "{out_sha}"}}')
    return exports, seeds


def test_geocodes_carry_the_address_their_run_recorded(tmp_path, monkeypatch):
    # The live input was regenerated after the run; the pin belongs to the input it was
    # geocoded from (found by sha256), so dbt sees 100 Main St, not 200.
    _, seeds = _geocode_env(tmp_path, monkeypatch)
    bs.build_geocodes()
    row = list(csv.DictReader((seeds / "geocodes.csv").open(encoding="utf-8")))[0]
    assert (row["subject_type"], row["subject_id"], row["geocoded_street"]) == ("candidate", "X-1", "100 Main St")


def test_geocodes_without_their_recorded_input_are_not_used(tmp_path, monkeypatch):
    # The receipt describes another output and there is no batch metadata: no input can
    # be proven, so no pins (an empty seed, not a guess).
    _, seeds = _geocode_env(tmp_path, monkeypatch, receipt_matches=False)
    bs.build_geocodes()
    assert list(csv.DictReader((seeds / "geocodes.csv").open(encoding="utf-8"))) == []
