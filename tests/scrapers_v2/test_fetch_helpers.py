"""URL normalization + candidate link discovery."""
from backend.scrapers_v2.fetch import candidate_links, normalize_url


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


def test_candidate_links_one_per_kind():
    html = """
        <a href="/about">A1</a>
        <a href="/about-us">A2</a>
    """
    links = candidate_links(html, "https://church.example.com/")
    assert "about" in links
    # First match wins; only one URL stored.
    assert sum(1 for k in links if k == "about") == 1
