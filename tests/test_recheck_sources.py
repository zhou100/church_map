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
