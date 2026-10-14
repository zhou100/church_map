"""R2 key + content hash determinism."""
from datetime import datetime, timezone

from backend.scrapers_v2.r2 import content_hash_of, r2_key_for


def test_sdk_has_finite_timeouts_and_total_retry_limit(monkeypatch):
    from backend.scrapers_v2 import r2
    seen = {}

    def client(*args, **kw):
        seen.update(kw)
        return object()
    monkeypatch.setattr(r2.boto3, 'client', client)
    bucket = r2.R2Client(account_id='fixture', access_key_id='fixture',
                         secret_access_key='fixture', bucket='fixture')
    bucket._ensure()
    config = seen['config']
    assert (config.connect_timeout, config.read_timeout) == (3, 10)
    assert config.retries == {'total_max_attempts': 2, 'mode': 'standard'}


def test_sdk_connection_failures_are_recoverable_r2_errors():
    import pytest
    from botocore.exceptions import EndpointConnectionError
    from backend.scrapers_v2.r2 import R2Client, R2Error

    class BrokenClient:
        def head_object(self, **kw):
            raise EndpointConnectionError(endpoint_url='https://fixture.test')
    bucket = R2Client()
    bucket._client = BrokenClient()
    with pytest.raises(R2Error):
        bucket.head('key')


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
