"""Brief v3.3 section A in the validator (no network).

WP-0001..0010: 433 of 624 congregations came back unresolved because only the homepage
was read, and 7 were marked active on a copyright year. From WP0011 the validator
requires the recorded deeper search and a dated status excerpt.
"""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "muse_handoff"))
import validate_returns as vr  # noqa: E402

FULL = ("activity checked: events=https://x.org/events; news=none; sermons=https://x.org/media; "
        "bulletin=none; facebook=no access; newest date seen=2024-03-01")


def errors(**row):
    base = dict(status="unresolved", notes="", status_excerpt="", facebook_page_url="", fb_last_post_date="")
    vr.problems.clear()
    vr.check_deep_search("w", {**base, **row})
    msgs = [m for level, _, m in vr.problems if level == "ERROR"]
    vr.problems.clear()
    return msgs


@pytest.mark.parametrize("task,applies", [("WP0011", True), ("WP0042", True), ("WP0010", False),
                                          ("WP0001", False), ("F", False), ("", False)])
def test_applies_from_wp0011_only(task, applies):
    assert vr.deep_search_applies(task) is applies


def test_unresolved_needs_the_activity_line():
    assert any("activity checked" in m for m in errors(notes="No dated evidence on the fetched homepage."))
    assert errors(notes="Homepage undated. " + FULL) == []


def test_every_key_must_be_recorded():
    msgs = errors(notes="activity checked: events=none; news=none; bulletin=none")
    assert msgs and "sermons" in msgs[0] and "facebook" in msgs[0]


@pytest.mark.parametrize("excerpt", ["Sunday, September 14, 2026 · Fall Kickoff Picnic",
                                     "Bulletin 10/12", "从8/2/26开始的主日学", "2026년 10월 5일 주일예배", "12 Oct · Youth night"])
def test_active_with_a_dated_excerpt_passes(excerpt):
    assert errors(status="active", status_excerpt=excerpt) == []


def test_active_on_a_copyright_year_fails():
    assert any("copyright" in m for m in errors(status="active", status_excerpt="© 2026 Grace Church. All rights reserved."))


def test_active_without_any_date_fails():
    assert any("no date" in m for m in errors(status="active", status_excerpt="Join us Sundays at 10am"))


def test_a_facebook_page_needs_its_last_post_date():
    page = "https://www.facebook.com/gracechurch"
    assert any("fb_last_post_date" in m for m in errors(notes=FULL, facebook_page_url=page))
    assert errors(notes=FULL, facebook_page_url=page, fb_last_post_date="2026-10-01") == []


# --- v3.4 S5: church directories are locate-only ---------------------------------------

@pytest.mark.parametrize("url,is_dir", [("https://www.churchfinder.com/churches/ca/sacramento", True),
                                        ("https://church.oursweb.net/x", True), ("https://app.church.org/find-a-church", True),
                                        ("https://gracechurch.org/visit", False), ("https://church.org.example.com/", False)])
def test_directory_hosts(url, is_dir):
    assert vr.is_directory_url(url) is is_dir


def _fact_errors(**row):
    vr.problems.clear()
    vr.check_common("w", row, None)
    msgs = [m for level, _, m in vr.problems if level == "ERROR"]
    vr.problems.clear()
    return msgs


def test_a_directory_is_never_a_facts_source():
    msgs = _fact_errors(phone="(916) 555-0100", phone_source_url="https://www.churchfinder.com/churches/ca/sacramento/grace",
                        phone_source_type="other", phone_excerpt="(916) 555-0100")
    assert any("church directory" in m for m in msgs)
    assert not any("church directory" in m for m in _fact_errors(
        phone="(916) 555-0100", phone_source_url="https://grace.example.org/contact", phone_source_type="own_site",
        phone_excerpt="Office (916) 555-0100"))


# Review of fb71910: the S5 ban ran only for v3 candidates; results.csv and service
# fixes have their own fact loops. It now sits in check_common, which every format uses.
LISTING = "https://www.churchfinder.com/churches/ca/sacramento/grace-church"


def _template_cols(name):
    return (Path(__file__).resolve().parents[1] / "muse_handoff" / name).read_text(encoding="utf-8").splitlines()[0].split(",")


def _write_rows(path, cols, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, restval="")
        w.writeheader()
        w.writerows(rows)


def test_a_results_row_citing_a_directory_is_rejected_through_main(tmp_path, capsys):
    cols = _template_cols("results_TEMPLATE_v3.csv")
    results, manifest = tmp_path / "results.csv", tmp_path / "manifest.csv"
    _write_rows(results, cols, [dict(church_id="1", entity_type="congregation", status="active",
                                     status_source_url=LISTING, status_source_type="other",
                                     status_excerpt="Sunday, October 5, 2026 · Harvest picnic",
                                     checked_at="2026-10-22T18:00:00Z")])
    _write_rows(manifest, ["church_id"], [dict(church_id="1")])
    vr.problems.clear()
    vr.main(["validate_returns.py", "ALL", str(results), "-", "--redo", "--manifest", str(manifest)])
    out = capsys.readouterr().out
    vr.problems.clear()
    assert "status_source_url is a church directory" in out


def test_a_service_fix_citing_a_directory_is_rejected(tmp_path):
    fixes = tmp_path / "service_fixes.csv"
    _write_rows(fixes, _template_cols("service_fixes_S_TEMPLATE.csv"),
                [dict(subject_type="church", subject_id="1", service_times_verbatim="Sunday 10:00 AM",
                      service_source_url=LISTING, service_source_type="other", service_excerpt="Sunday 10:00 AM",
                      checked_at="2026-10-22T18:00:00Z")])
    vr.problems.clear()
    vr.check_service_fixes(fixes, None)
    msgs = [m for level, _, m in vr.problems if level == "ERROR"]
    vr.problems.clear()
    assert any("service_source_url is a church directory" in m for m in msgs)
