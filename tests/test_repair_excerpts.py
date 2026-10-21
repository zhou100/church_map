"""analytics/scripts/repair_excerpts.py: finding a verbatim passage that holds the fact (no network)."""
import importlib.util
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1] / "analytics" / "scripts"
sys.path.insert(0, str(_DIR))
_spec = importlib.util.spec_from_file_location("repair_excerpts", _DIR / "repair_excerpts.py")
rx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rx)
import recheck_sources as rs  # noqa: E402

PAGE = rx.collapse("""Welcome to Holy Angels Parish. Parish Office: 107 San Pedro Road, Colma, CA 94014.
Call us at (650) 755-0478 any weekday. Mass Schedule: Saturday 5:00 PM Vigil; Sunday 8:00 AM, 10:00 AM
and 12:00 PM (Spanish). Confessions Saturday 4:00 PM. Our community has served Colma since 1914.""")


def _verifies(excerpt):
    return rs.match(excerpt, PAGE)[0] == "verified"


def test_address_passage_is_verbatim_and_verifies():
    ex = rx.find_address(PAGE, "107 San Pedro Rd")
    assert ex and "107 San Pedro Road" in ex and len(ex) <= 200 and ex in PAGE and _verifies(ex)


def test_phone_passage():
    ex = rx.find_phone(PAGE, "+1-650-755-0478")
    assert ex and "(650) 755-0478" in ex and ex in PAGE and _verifies(ex)


def test_service_schedule_assembled_from_separate_times_is_not_repaired():
    # The record isn't on the page word for word: matching hours alone could pair them
    # with the wrong day or activity, so the fact is left for review instead.
    assert rx.find_service(PAGE, "Sat 5 pm; Sun 8 am, 10 am, 12 pm") is None
    ex = rx.find_service(PAGE, "Sunday 8:00 AM, 10:00 AM and 12:00 PM (Spanish)")
    assert ex and "Sunday 8:00 AM, 10:00 AM and 12:00 PM (Spanish)" in ex and _verifies(ex)


def test_fact_not_on_page_is_not_repaired():
    assert rx.find_address(PAGE, "108 San Pedro Road") is None
    assert rx.find_phone(PAGE, "650-755-0479") is None
    assert rx.find_service(PAGE, "Sunday 9:30 am") is None


def test_window_never_exceeds_cap():
    long = "x " * 300 + "123 Main Street" + " y" * 300
    ex = rx.find_address(rx.collapse(long), "123 Main St")
    assert ex and len(ex) <= 200 and "123 Main Street" in ex


def test_email_is_cut_out_of_the_passage():
    page = rx.collapse("Contact us 650-282-7718 info@foothills-church.org 461 Orange Avenue Los Altos, CA 94022")
    ex = rx.find_phone(page, "650-282-7718")
    assert ex and "@" not in ex and "650-282-7718" in ex
    ex = rx.find_address(page, "461 Orange Avenue")
    assert ex and "@" not in ex and "461 Orange Avenue" in ex


def test_blocked_source_is_resourced_to_the_churchs_own_site(monkeypatch):
    import asyncio

    rows = [{"candidate_ref": "D-001", "official_url": "https://stlucy.example.org/", "street_address": "2350 Winchester Blvd",
             "address_source_url": "https://www.dsj.org/parishes/", "address_source_type": "denomination",
             "address_excerpt": "St. Lucy 2350 Winchester Blvd", "phone": "408-555-0100",
             "phone_source_url": "https://www.dsj.org/parishes/", "phone_source_type": "denomination",
             "phone_excerpt": "408-555-0100", "notes": ""}]
    report = [{"row_key": "D-001", "group": "address", "verdict": "fetch_failed", "source_url": "https://www.dsj.org/parishes/"},
              {"row_key": "D-001", "group": "phone", "verdict": "fetch_failed", "source_url": "https://www.dsj.org/parishes/"}]

    async def fake_pages(fetcher, url):
        return [("https://stlucy.example.org/contact", rx.collapse("Visit us at 2350 Winchester Blvd, Campbell, CA 95008"))]

    monkeypatch.setattr(rx, "official_pages", fake_pages)
    log = []
    asyncio.run(rx.resource_blocked(rows, "candidate_ref", report, log, "2026-10-20"))
    r = rows[0]
    assert r["address_source_url"] == "https://stlucy.example.org/contact" and r["address_source_type"] == "own_site"
    assert "2350 Winchester Blvd" in r["address_excerpt"]
    # The phone isn't on the church's site: left exactly as it was.
    assert r["phone_source_url"] == "https://www.dsj.org/parishes/"
    assert [x["action"] for x in log] == ["resourced", "not_resourced"]



def test_blocked_service_answer_is_resourced_via_its_subjects_website(monkeypatch):
    # An S answer row has no official_url; the website comes from the subject's record.
    import asyncio

    rows = [{"subject_type": "candidate", "subject_id": "D-080", "service_times_verbatim": "Sunday 9:00 AM English",
             "service_languages": "English", "service_source_url": "https://www.dsj.org/mass-prayer-services/",
             "service_source_type": "denomination", "service_excerpt": "Sunday Schedule … 9:00 AM English",
             "notes": ""}]
    report = [{"row_key": "D-080", "group": "service", "verdict": "fetch_failed",
               "source_url": "https://www.dsj.org/mass-prayer-services/"}]
    seen = []

    async def fake_pages(fetcher, url):
        seen.append(url)
        return [("https://croatian.example.org/mass", rx.collapse("Mass times: Sunday 9:00 AM English"))]

    monkeypatch.setattr(rx, "official_pages", fake_pages)
    log = []
    asyncio.run(rx.resource_blocked(rows, "subject_id", report, log, "2026-10-21",
                                    {"D-080": "https://croatian.example.org/"}))
    assert seen == ["https://croatian.example.org/"]
    assert rows[0]["service_source_url"] == "https://croatian.example.org/mass" and "official_url" not in rows[0]

def test_names_near_the_fact_are_cut_out():
    page = rx.collapse("Children's Ministry | 8:00pm 137 Dempsey Road Milpitas, Ca 95035 Contact Sam Shin | Senior Pastor")
    ex = rx.find_address(page, "137 Dempsey Rd")
    assert ex and "137 Dempsey Road" in ex and "Shin" not in ex and "Pastor" not in ex
    page = rx.collapse("Pastor John Smith welcomes you. 461 Orange Avenue Los Altos, CA 94022")
    ex = rx.find_address(page, "461 Orange Avenue")
    assert ex and "Smith" not in ex and ex.startswith("461 Orange Avenue")


def test_same_number_and_first_word_on_another_street_is_not_repaired():
    page = rx.collapse("Our sister parish is at 107 San Mateo Avenue, San Bruno. Mass times are below.")
    assert rx.find_address(page, "107 San Pedro Road") is None
    page = rx.collapse("Office: 107 San Pedro Road, Colma, CA 94014")
    assert "107 San Pedro Road" in rx.find_address(page, "107 San Pedro Rd")


def test_repair_log_keeps_history(tmp_path):
    log = tmp_path / "repairs" / "x.csv"
    rx.append_log(log, [{"row_key": "1", "group": "address", "action": "repaired"}])
    rx.append_log(log, [{"row_key": "2", "group": "phone", "action": "repaired"}])
    import csv
    rows = list(csv.DictReader(log.open(encoding="utf-8")))
    assert [r["row_key"] for r in rows] == ["1", "2"] and all(r["run_id"] and r["logged_at"] for r in rows)


def test_repair_finds_ordinal_and_saint_spellings_but_not_other_streets():
    page = rx.collapse("Address : 1971 Saint Lawrence Dr. Santa Clara, 95051. Also 1555 39 Avenue San Francisco")
    assert "1971 Saint Lawrence Dr" in rx.find_address(page, "1971 St. Lawrence Dr.")
    assert "1555 39 Avenue" in rx.find_address(page, "1555 39th Avenue")
    assert rx.find_address(rx.collapse("1860 Grant Road Los Altos"), "1860 Grant Ave") is None


def test_service_repair_requires_the_recorded_schedule_not_just_the_hour():
    page = rx.collapse("Saturday Bible study 10 AM; Sunday worship 11 AM. Everyone welcome.")
    assert rx.find_service(page, "Sunday worship 10 AM") is None
    page = rx.collapse("Welcome! Sunday Worship: 10:00 AM in the sanctuary. Children's church follows.")
    ex = rx.find_service(page, "Sunday Worship 10:00 AM")
    assert ex and "Sunday Worship: 10:00 AM" in ex
