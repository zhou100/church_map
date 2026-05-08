"""R2 key + content hash determinism."""
from datetime import datetime, timezone

from backend.scrapers_v2.r2 import content_hash_of, r2_key_for


def test_content_hash_stable():
    a = content_hash_of("Hello, world.")
    b = content_hash_of("Hello, world.")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_content_hash_differs_on_content():
    assert content_hash_of("a") != content_hash_of("b")


def test_r2_key_format():
    fetched = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
    chash = "abc123"
    key = r2_key_for(42, chash, fetched)
    assert key == "raw_html/42/2026-05-08/abc123.html"


def test_r2_key_uses_utc_date():
    fetched = datetime(2026, 5, 8, 23, 30, 0, tzinfo=timezone.utc)
    key = r2_key_for(1, "deadbeef", fetched)
    assert "2026-05-08" in key
