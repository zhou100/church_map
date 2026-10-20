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


def test_service_passage_must_hold_every_time():
    ex = rx.find_service(PAGE, "Sat 5 pm; Sun 8 am, 10 am, 12 pm")
    assert ex and all(t in ex for t in ("5:00 PM", "8:00 AM", "10:00 AM", "12:00 PM")) and _verifies(ex)


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


def test_names_near_the_fact_are_cut_out():
    page = rx.collapse("Children's Ministry | 8:00pm 137 Dempsey Road Milpitas, Ca 95035 Contact Sam Shin | Senior Pastor")
    ex = rx.find_address(page, "137 Dempsey Rd")
    assert ex and "137 Dempsey Road" in ex and "Shin" not in ex and "Pastor" not in ex
    page = rx.collapse("Pastor John Smith welcomes you. 461 Orange Avenue Los Altos, CA 94022")
    ex = rx.find_address(page, "461 Orange Avenue")
    assert ex and "Smith" not in ex and ex.startswith("461 Orange Avenue")
