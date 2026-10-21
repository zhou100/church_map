"""Matching rules for analytics/scripts/recheck_sources.py (no network)."""
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "analytics" / "scripts" / "recheck_sources.py"
_spec = importlib.util.spec_from_file_location("recheck_sources", _PATH)
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

PAGE = """
<html><head><script>var x = "1130 Balclutha Drive";</script></head>
<body><h1>Island United Church</h1>
<p>1130 Balclutha Drive,<br/>Foster City, CA&nbsp;94404</p>
<p>Join the Sunday Celebration</p><div>Every Sunday at 10 am Pacific</div>
<p>彌撒時間﹕ 第二,第四及第五個主日下午一時半</p>
</body></html>
"""


def text():
    return rs.page_text(PAGE.encode(), "text/html; charset=utf-8", "https://example.org/")


def test_exact_match_ignores_whitespace_and_line_breaks():
    assert rs.match("1130 Balclutha Drive, Foster City, CA 94404", text())[0] == "verified"


def test_excerpt_joined_with_slash_is_checked_per_segment():
    assert rs.match("Join the Sunday Celebration / Every Sunday at 10 am Pacific", text())[0] == "verified"
    # Two real fragments that are not adjacent on the page still verify, fragment by fragment.
    v, found, total, _ = rs.match("Island United Church / Every Sunday at 10 am Pacific", text())
    assert (v, found, total) == ("verified", 2, 2)


def test_paraphrased_excerpt_is_not_verified():
    # What happened in task CN: an excerpt rewritten with Arabic time tokens.
    assert rs.match("Every Sunday at 10:00 AM (Pacific)", text())[0] == "not_found"


def test_one_invented_segment_makes_it_partial():
    assert rs.match("Join the Sunday Celebration / Childcare available at 10 am", text())[0] == "partial"


def test_script_text_does_not_count():
    page = "<html><head><script>var x='Sunday 9am Mandarin';</script></head><body>Welcome</body></html>"
    assert rs.match("Sunday 9am Mandarin", rs.page_text(page.encode(), "text/html", "https://x.org"))[0] == "not_found"


def test_cjk_excerpt_verbatim_matches():
    assert rs.match("第二,第四及第五個主日下午一時半", text())[0] == "verified"


def test_markdown_from_agent_extraction_is_ignored():
    assert rs.match("### Island United Church", text())[0] == "verified"


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.0.0.5", "169.254.169.254"])
def test_private_hosts_are_not_public(host):
    assert rs.is_public(host) is False


def test_zero_width_characters_are_ignored():
    page = "<html><body><p>(650) 349-3544​</p><p>Sun​day 10am</p></body></html>"
    t = rs.page_text(page.encode(), "text/html; charset=utf-8", "https://x.org")
    assert rs.match("(650) 349-3544", t)[0] == "verified"
    assert rs.match("Sunday 10am", t)[0] == "verified"


def test_results_stay_aligned_with_their_urls(monkeypatch):
    """Regression: results were zipped against an unordered set and checked on the wrong page."""
    import asyncio

    pages = {"https://b.org/": "<p>Beta Church 2 Elm St</p>", "https://a.org/": "<p>Alpha Church 1 Oak St</p>"}

    async def fake_fetch(self, url):
        return {"verdict": "fetched", "text": rs.page_text(pages[url].encode(), "text/html", url), "http_status": 200, "final_url": url}

    monkeypatch.setattr(rs.Fetcher, "fetch", fake_fetch)
    tmp = Path(__file__).parent / "_recheck_tmp.csv"
    out_dir = rs.OUT_DIR
    try:
        tmp.write_text("church_id,current_name,address_source_url,address_source_type,address_excerpt\n"
                       "1,Alpha,https://a.org/,own_site,1 Oak St\n2,Beta,https://b.org/,own_site,2 Elm St\n", encoding="utf-8")
        rs.OUT_DIR = tmp.parent / "_recheck_out"
        asyncio.run(rs.run([tmp]))
        import csv
        rows = list(csv.DictReader((rs.OUT_DIR / "_recheck_tmp.csv").open(encoding="utf-8")))
        assert [r["verdict"] for r in rows] == ["verified", "verified"]
    finally:
        tmp.unlink(missing_ok=True)
        import shutil
        shutil.rmtree(tmp.parent / "_recheck_out", ignore_errors=True)
        rs.OUT_DIR = out_dir


def test_fragments_joined_with_dashes_and_semicolons():
    page = "<p>Join Us Sundays</p><p>SUNDAY WORSHIP IN ENGLISH 8:30 AM - In-Person Only</p><p>Korean 11 AM</p>"
    t = rs.page_text(page.encode(), "text/html; charset=utf-8", "https://x.org")
    assert rs.match("Join Us Sundays — SUNDAY WORSHIP IN ENGLISH 8:30 AM - In-Person Only; Korean 11 AM", t)[0] == "verified"


def test_description_instead_of_quote_is_flagged():
    t = rs.page_text(b"<p>Welcome to our church</p>", "text/html", "https://x.org")
    assert rs.match("homepage carries current service schedule and a 2026/10-dated image", t)[0] == "not_an_excerpt"


# --- Review of PR #41, issue 1: short fragments must not be dropped -----------------

def _t(html):
    return rs.page_text(html.encode(), "text/html; charset=utf-8", "https://x.org")


def test_short_time_fragment_is_not_dropped():
    assert rs.match("Sunday worship / 9 am", _t("<p>Sunday worship at 11 am</p>"))[0] != "verified"


def test_zip_fragment_must_match_exactly():
    page = _t("<p>123 Main St</p><p>Los Altos, CA 94024</p>")
    assert rs.match("123 Main St / Los Altos, CA 94022", page)[0] != "verified"
    assert rs.match("123 Main St / 94022", page)[0] != "verified"
    assert rs.match("123 Main St / 94024", page)[0] == "verified"


def test_number_is_not_matched_inside_a_longer_number():
    page = _t("<p>1123 Main St, Palo Alto</p><p>Phone 650-555-01234</p>")
    assert rs.match("123 Main St", page)[0] != "verified"
    assert rs.match("650-555-0123", page)[0] != "verified"


def test_short_fragment_with_its_context_still_verifies():
    page = _t("<p>Sunday worship</p><p>9 am</p>")
    assert rs.match("Sunday worship / 9 am", page)[0] == "verified"


def test_short_fragment_far_from_its_context_does_not_verify():
    page = _t("<p>Sunday worship at 11 am</p>" + "<p>filler text</p>" * 60 + "<p>Bible study 9 am</p>")
    assert rs.match("Sunday worship / 9 am", page)[0] != "verified"


def test_short_latin_word_is_not_matched_inside_a_word():
    assert rs.match("Main Street / am", _t("<p>Main Street amen</p>"))[0] != "verified"


# --- Review of PR #41, issue 4: robots.txt redirects ------------------------------

import asyncio  # noqa: E402

import httpx  # noqa: E402


def _robots_for(handler, monkeypatch, public=lambda host: True):
    monkeypatch.setattr(rs, "is_public", public)
    monkeypatch.setattr(rs, "PER_HOST_DELAY_S", 0)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await rs.Fetcher(client)._robots("https://church.example.org/private/page")

    return asyncio.run(go())


def test_redirected_robots_is_followed(monkeypatch):
    def handler(req):
        if req.url.host == "church.example.org":
            return httpx.Response(301, headers={"location": "https://cdn.example.org/robots.txt"})
        return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")

    rp = _robots_for(handler, monkeypatch)
    assert not rp.can_fetch(rs.USER_AGENT, "https://church.example.org/private/page")
    assert rp.can_fetch(rs.USER_AGENT, "https://church.example.org/about")


def test_missing_robots_allows(monkeypatch):
    rp = _robots_for(lambda req: httpx.Response(404), monkeypatch)
    assert rp.can_fetch(rs.USER_AGENT, "https://church.example.org/private/page")


def test_unreachable_robots_disallows(monkeypatch):
    rp = _robots_for(lambda req: httpx.Response(503), monkeypatch)
    assert not rp.can_fetch(rs.USER_AGENT, "https://church.example.org/about")


def test_robots_redirect_to_private_host_disallows(monkeypatch):
    def handler(req):
        return httpx.Response(302, headers={"location": "http://internal.example/robots.txt"})

    rp = _robots_for(handler, monkeypatch, public=lambda host: host != "internal.example")
    assert not rp.can_fetch(rs.USER_AGENT, "https://church.example.org/about")


def test_robots_redirect_loop_disallows(monkeypatch):
    rp = _robots_for(lambda req: httpx.Response(301, headers={"location": str(req.url)}), monkeypatch)
    assert not rp.can_fetch(rs.USER_AGENT, "https://church.example.org/about")


def test_punctuation_and_table_borders_do_not_matter():
    page = _t("<p>+1 650-579-5528</p><p>1430 Palm Drive</p><p>Burlingame, California 94010</p>")
    assert rs.match("1430 Palm Drive, Burlingame, California 94010", page)[0] == "verified"
    assert rs.match("| 1430 Palm Drive | Burlingame, California 94010 |", page)[0] == "verified"


def test_adjacent_numbers_do_not_merge():
    page = _t("<p>Call 650-579-5528 1430 Palm Drive</p>")
    assert rs.match("528 1430 Palm Drive", page)[0] != "verified"


def test_digit_letter_spacing_does_not_matter():
    page = _t("<p>Sunday Worship 11:15am</p><p>主日崇拜 下午1:30</p>")
    assert rs.match("Sunday Worship 11:15 am", page)[0] == "verified"
    assert rs.match("主日崇拜 下午 1:30", page)[0] == "verified"
    assert rs.match("Sunday Worship 1:15 am", page)[0] != "verified"


def test_word_cut_by_the_200_char_cap_still_verifies():
    text = "Service starts at 9:30am in our Sanctuary, with child care available for families. " * 3
    text += "Sunday school classes are conducted in English"
    excerpt = text[:200]
    assert not excerpt.endswith(" ") and rs.match(excerpt, _t(f"<p>{text}</p>"))[0] == "verified"


def test_number_cut_by_the_cap_is_not_forgiven():
    page = _t("<p>" + "Our address and phone number are listed here for visitors " * 3 + "650-555-0199</p>")
    excerpt = ("Our address and phone number are listed here for visitors " * 3 + "650-555-01")[:200]
    assert rs.match(excerpt, page)[0] != "verified"


def test_pdf_like_spacing_with_whole_numbers_verifies():
    page = _t("<p>LordsGrace Christian Church 1101 San Antonio Rd MountainView, CA 94043</p>")
    assert rs.match("Lords Grace Christian Church 1101 San Antonio Rd Mountain View, CA 94043", page)[0] == "verified"
    assert rs.match("Lords Grace Christian Church 101 San Antonio Rd Mountain View, CA 94043", page)[0] != "verified"


# --- Review of e9980b51, issue 1: number boundaries belong to the same occurrence -----

def test_house_number_inside_a_longer_number_with_a_decoy_elsewhere():
    page = _t("<p>Visit us at 123 Main Street, Palo Alto.</p><p>Established 23 years ago.</p>")
    assert rs.match("23 Main Street", page)[0] != "verified"
    assert rs.match("123 Main Street", page)[0] == "verified"


def test_squash_keeps_numbers_apart():
    assert rs.squash("Call 650-579-5528 1430 Palm Drive") == "call650 579 5528 1430palmdrive"
    page = _t("<p>Sun<span>day</span> Wor<b>ship</b> at 1430 Palm Drive</p>")
    assert rs.match("Sunday Worship", page)[0] == "verified"


def test_deleted_page_is_source_gone_not_a_fetch_failure(monkeypatch):
    import asyncio
    import httpx
    monkeypatch.setattr(rs, "is_public", lambda host: True)
    monkeypatch.setattr(rs, "PER_HOST_DELAY_S", 0)

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(410 if req.url.path == "/gone" else 503)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            f = rs.Fetcher(c)
            return await f.fetch("https://church.example.org/gone"), await f.fetch("https://church.example.org/busy")

    gone, busy = asyncio.run(go())
    assert gone["verdict"] == "source_gone" and busy["verdict"] == "fetch_failed" and busy["http_status"] == 503
