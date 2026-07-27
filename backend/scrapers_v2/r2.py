"""Cloudflare R2 client (S3-compatible, via boto3).

R2 is S3 API with a different endpoint and no region semantics. boto3 handles
it cleanly with `endpoint_url` and `region_name='auto'`. We use signature v4
because R2 requires it.

Keys are deterministic:
    raw_html/{church_id}/{YYYY-MM-DD}/{content_hash}.html

The date segment is the fetch date in UTC. content_hash is sha256 of the
cleaned text (not the raw HTML) so two fetches that yield the same extracted
text dedupe even if cookies/timestamps in the HTML differ.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    boto3 = None
    Config = None
    ClientError = Exception


class R2Error(Exception):
    pass


class R2NotFound(R2Error):
    """The key is genuinely absent from the bucket.

    Split out from R2Error because the two need opposite handling: a missing
    object is never coming back, so whatever depends on it has to be re-fetched
    from the origin; anything else (auth, throttling, a 5xx from Cloudflare) is
    the bucket being temporarily unreachable and must be retried instead of
    treated as "no content".
    """


def content_hash_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def r2_key_for(church_id: int, content_hash: str, fetched_at: datetime | None = None) -> str:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    date = fetched_at.strftime("%Y-%m-%d")
    return f"raw_html/{church_id}/{date}/{content_hash}.html"


class R2Client:
    """Thin wrapper. One client per process; lazy-init."""

    def __init__(
        self,
        *,
        account_id: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        bucket: str | None = None,
    ):
        self.account_id = account_id or os.environ.get("R2_ACCOUNT_ID", "")
        self.access_key_id = access_key_id or os.environ.get("R2_ACCESS_KEY_ID", "")
        self.secret_access_key = secret_access_key or os.environ.get("R2_SECRET_ACCESS_KEY", "")
        self.bucket = bucket or os.environ.get("R2_BUCKET", "")
        self._client: Any = None

    def _ensure(self) -> Any:
        if self._client is not None:
            return self._client
        if not all([self.account_id, self.access_key_id, self.secret_access_key, self.bucket]):
            raise R2Error("R2 credentials missing (R2_ACCOUNT_ID/ACCESS_KEY_ID/SECRET_ACCESS_KEY/BUCKET)")
        if boto3 is None:
            raise R2Error("boto3 is not installed")
        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
        )
        return self._client

    @staticmethod
    def _is_missing(e: Any) -> bool:
        code = e.response.get("Error", {}).get("Code", "") if hasattr(e, "response") else ""
        return code in ("404", "NoSuchKey", "NotFound")

    def head(self, key: str) -> bool:
        try:
            self._ensure().head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if self._is_missing(e):
                return False
            raise R2Error(f"R2 head failed: {e}") from e

    def put_html(self, key: str, html: bytes) -> None:
        try:
            self._ensure().put_object(
                Bucket=self.bucket,
                Key=key,
                Body=html,
                ContentType="text/html; charset=utf-8",
            )
        except ClientError as e:
            raise R2Error(f"R2 put failed: {e}") from e

    def get_html(self, key: str) -> bytes:
        try:
            r = self._ensure().get_object(Bucket=self.bucket, Key=key)
            return r["Body"].read()
        except ClientError as e:
            if self._is_missing(e):
                raise R2NotFound(f"R2 key absent: {key}") from e
            raise R2Error(f"R2 get failed for {key}: {e}") from e
