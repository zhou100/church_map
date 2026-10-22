"""Brief v3.3 section A in the validator (no network).

WP-0001..0010: 433 of 624 congregations came back unresolved because only the homepage
was read, and 7 were marked active on a copyright year. From WP0011 the validator
requires the recorded deeper search and a dated status excerpt.
"""
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
