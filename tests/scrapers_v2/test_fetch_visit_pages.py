"""Fetch archives the pages the visit-facts stage needs (kids, youth, childcare,
contact, events, news, sermons) without changing what website_v3 reads."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import httpx

from backend.db.repository import WEBSITE_V3_KINDS
from backend.scrapers_v2 import fetch as fetch_mod

HOME = """<html><body>
  <a href="/about">About</a><a href="/beliefs">Beliefs</a><a href="/ministries">Ministries</a>
  <a href="/plan-your-visit">Plan your visit</a><a href="/kids">Kids</a><a href="/students">Students</a>
  <a href="/preschool">Preschool</a><a href="/contact-us">Contact</a><a href="/events">Events</a>
  <a href="/blog">Blog</a><a href="/sermons">Sermons</a><a href="https://other.example/kids">x</a>
  <p>Sunday worship 10am.</p></body></html>"""


def test_candidate_links_finds_visit_pages_and_keeps_the_v3_kinds():
    links = fetch_mod.candidate_links(HOME, "https://grace.example/")
    assert {k: v.rsplit("/", 1)[-1] for k, v in links.items()} == {
        "about": "about", "beliefs": "beliefs", "ministries": "ministries", "services": "plan-your-visit",
        "kids": "kids", "youth": "students", "childcare": "preschool", "contact": "contact-us",
        "events": "events", "news": "blog", "sermons": "sermons",
    }


def test_a_kids_link_seen_before_ministries_stays_a_v3_page():
    # Unchanged behaviour: website_v3's "ministries" claims the first matching link.
    links = fetch_mod.candidate_links('<a href="/kids">K</a><a href="/sunday-school">S</a>', "https://a.example/")
    assert links["ministries"].endswith("/kids") and links["kids"].endswith("/sunday-school")


def test_sunday_school_is_a_kids_page_not_a_school():
    links = fetch_mod.candidate_links('<a href="/ministries">M</a><a href="/sunday-school">S</a>',
                                      "https://a.example/")
    assert links["kids"].endswith("/sunday-school") and "childcare" not in links


class Repo:
    def __init__(self):
        self.inserts = []

    async def get_robots(self, host):
        return {"body": ""}

    async def insert_artifact(self, **kw):
        self.inserts.append(kw)
        return 1


class R2:
    def head(self, key):
        return True


def _fetch(monkeypatch, *, html=HOME, **kw):
    monkeypatch.setattr(fetch_mod, "PER_DOMAIN_DELAY_S", 0)
    monkeypatch.setattr(fetch_mod, "extract_clean_text", lambda html: "Some page text.")

    def handler(req):
        return httpx.Response(200, content=html.encode() if req.url.path == "/" else b"<p>page</p>")

    async def main():
        repo = Repo()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            n = await fetch_mod.fetch_church(client, repo, R2(), 7, "https://grace.example/", 1, **kw)
        return n, [r["kind"] for r in repo.inserts]

    return asyncio.run(main())


def test_visit_pages_have_their_own_cap_after_the_v3_pages(monkeypatch):
    n, kinds = _fetch(monkeypatch)
    assert kinds == ["homepage", "about", "beliefs", "ministries", "kids", "youth", "childcare", "contact"]
    assert n == 8
    assert set(kinds[:4]) <= set(WEBSITE_V3_KINDS) and not set(kinds[4:]) & set(WEBSITE_V3_KINDS)


def test_max_visit_pages_zero_is_the_old_fetch(monkeypatch):
    _, kinds = _fetch(monkeypatch, max_visit_pages=0)
    assert kinds == ["homepage", "about", "beliefs", "ministries"]


def test_every_visit_kind_is_outside_website_v3():
    assert not {k for k, _ in fetch_mod.VISIT_PATHS} & set(WEBSITE_V3_KINDS)
    assert {k for k, _ in fetch_mod.CANDIDATE_PATHS} | {"homepage"} == set(WEBSITE_V3_KINDS)


class BatchRepo(Repo):
    con = SimpleNamespace(transaction=nullcontext)

    async def churches_due_for_fetch(self, limit, fresh_days):
        return [{"church_id": i, "website": f"https://c{i}.example/"} for i in range(5)]


def test_the_batch_stops_starting_churches_at_the_time_budget(monkeypatch):
    seen = []

    async def fake_fetch(client, repo, r2, church_id, website, crawl_run_id, **kw):
        seen.append(church_id)
        return 1

    ticks = iter([0, 0, 100, 250, 999, 999, 999])  # start, then one reading per church
    monkeypatch.setattr(fetch_mod, "fetch_church", fake_fetch)
    out = asyncio.run(fetch_mod.run_fetch_batch(BatchRepo(), None, batch_size=5, fresh_days=30,
                                                crawl_run_id=1, time_budget_s=300,
                                                clock=lambda: next(ticks)))
    assert seen == [0, 1, 2]
    assert (out["rows_processed"], out["rows_ok"], out["deferred"]) == (3, 3, 2)


def test_visit_pages_match_with_a_file_suffix_and_run_together_names():
    # Slugs seen on 2026-11-03 in a 100-site sample that the first patterns missed.
    links = fetch_mod.candidate_links(
        '<a href="/children.html">C</a><a href="/youthministry">Y</a><a href="/earlychildhood">E</a>',
        "https://a.example/")
    assert links["kids"].endswith("/children.html")
    assert links["youth"].endswith("/youthministry") and links["childcare"].endswith("/earlychildhood")
    # website_v3's kinds still need the bare slug: "about.html" stays unmatched as before.
    assert "about" not in fetch_mod.candidate_links('<a href="/about.html">A</a>', "https://a.example/")


def test_repeated_navigation_does_not_hide_a_distinct_kids_page(monkeypatch):
    html = ('<a href="/kids">Kids</a><a href="https://grace.example/kids#mobile">Kids mobile</a>'
            '<a href="/children">Children</a><a href="/students">Students</a>'
            '<a href="/preschool">Preschool</a><a href="/contact">Contact</a>')
    links = fetch_mod.candidate_links(html, "https://grace.example/")
    assert links["ministries"] == "https://grace.example/kids"
    assert links["kids"] == "https://grace.example/children"
    n, kinds = _fetch(monkeypatch, html=html)
    assert n == 6
    assert kinds == ["homepage", "ministries", "kids", "youth", "childcare", "contact"]


def test_budget_interrupts_a_church_and_counts_it_as_deferred(monkeypatch):
    seen = []
    cancelled = []

    async def fake_fetch(client, repo, r2, church_id, website, crawl_run_id, **kw):
        seen.append(church_id)
        if church_id == 1:
            try:
                await asyncio.sleep(0.2)
            finally:
                cancelled.append(church_id)
        return 1

    monkeypatch.setattr(fetch_mod, "fetch_church", fake_fetch)
    ticks = iter([0, 0, 419, 1000])
    # Scale the real timer down without waiting hundreds of seconds.
    timeout = asyncio.timeout
    monkeypatch.setattr(fetch_mod.asyncio, "timeout", lambda seconds: timeout(seconds / 1000))
    repo = BatchRepo()
    out = asyncio.run(fetch_mod.run_fetch_batch(
        repo, None, batch_size=5, fresh_days=30, crawl_run_id=1,
        time_budget_s=420, clock=lambda: next(ticks)))
    assert seen == [0, 1] and cancelled == [1]
    assert (out["rows_processed"], out["rows_ok"], out["rows_error"], out["deferred"]) == (1, 1, 0, 4)
    assert repo.inserts == []  # deadline deferral must not trigger the 48-hour failure backoff


def test_deadline_interrupts_the_real_page_retry(monkeypatch):
    requests = []
    deadlines = []
    real_timeout = asyncio.timeout

    def timeout(seconds):
        deadline = real_timeout(seconds)
        deadlines.append(deadline)
        return deadline

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/":
            return httpx.Response(200, content=HOME.encode())
        # Homepage is already recorded. Expire as the first subpage fails;
        # the production retry delay must be interrupted before another GET.
        deadlines[-1].reschedule(asyncio.get_running_loop().time())
        raise httpx.ReadTimeout("slow subpage")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(fetch_mod.httpx, "AsyncClient", lambda **kw: client)
    monkeypatch.setattr(fetch_mod.asyncio, "timeout", timeout)
    monkeypatch.setattr(fetch_mod, "PER_DOMAIN_DELAY_S", 0)
    monkeypatch.setattr(fetch_mod, "extract_clean_text", lambda html: "Some page text.")
    out = asyncio.run(fetch_mod.run_fetch_batch(
        BatchRepo(), R2(), batch_size=5, fresh_days=30, crawl_run_id=1))
    assert requests == ["/", "/about"]
    assert (out["rows_processed"], out["rows_error"], out["deferred"]) == (0, 0, 5)
