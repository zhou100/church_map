"""URL normalization + candidate link discovery."""
import asyncio

from backend.scrapers_v2.fetch import candidate_links, fetch_church, normalize_url


def test_normalize_adds_https():
    assert normalize_url("example.com") == "https://example.com/"


def test_normalize_keeps_path():
    assert normalize_url("https://example.com/about") == "https://example.com/about"


def test_normalize_strips_query_and_fragment():
    assert normalize_url("https://example.com/x?y=1#z") == "https://example.com/x"


def test_normalize_rejects_garbage():
    assert normalize_url("not a url") is None
    assert normalize_url("") is None
    assert normalize_url("http://nodot") is None


def test_candidate_links_finds_about_and_beliefs():
    html = """
        <a href="/about-us">About</a>
        <a href="/what-we-believe">Beliefs</a>
        <a href="https://other.example.com/about">External</a>
    """
    links = candidate_links(html, "https://church.example.com/")
    assert links["about"].endswith("/about-us")
    assert links["beliefs"].endswith("/what-we-believe")
    # External host should not appear
    assert all("other.example.com" not in v for v in links.values())


class _FakeRepo:
    def __init__(self):
        self.inserts = []

    async def insert_artifact(self, **kw):
        self.inserts.append(kw)
        return 1


def test_fetch_church_records_bad_url_for_backoff():
    """A church with a malformed website must still write an artifact row,
    so the latest_attempt CTE backoff in churches_due_for_fetch keeps it from
    being re-selected every cron run."""
    repo = _FakeRepo()
    written = asyncio.run(
        fetch_church(
            client=None,  # unused on the bad-url path
            repo=repo,
            r2=None,      # unused on the bad-url path
            church_id=42,
            website="not a url",
            crawl_run_id=7,
        )
    )
    assert written == 0
    assert len(repo.inserts) == 1
    row = repo.inserts[0]
    assert row["church_id"] == 42
    assert row["http_status"] == 0
    assert row["fetch_error"] == "bad-url"
    assert row["content_hash"] is None
    assert row["r2_key"] is None
    assert row["crawl_run_id"] == 7


def test_candidate_links_one_per_kind():
    html = """
        <a href="/about">A1</a>
        <a href="/about-us">A2</a>
    """
    links = candidate_links(html, "https://church.example.com/")
    assert "about" in links
    # First match wins; only one URL stored.
    assert sum(1 for k in links if k == "about") == 1
