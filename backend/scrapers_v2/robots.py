"""Postgres-backed robots.txt cache.

24h TTL by default. Failures (timeouts, 5xx) are cached as empty body, which
RobotFileParser treats as fully allowed. 404 is treated the same — RFC 9309
says 404 means no restrictions.
"""
from __future__ import annotations

import urllib.parse
import urllib.robotparser
from typing import Any

import httpx

from backend.db.repository import CrawlRepository

ROBOTS_TTL_SECONDS = 24 * 3600
HTTP_TIMEOUT_S = 10.0


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


async def get_parser(
    repo: CrawlRepository,
    client: Any,  # httpx.AsyncClient
    base_url: str,
) -> urllib.robotparser.RobotFileParser:
    """Return a parser for the host of base_url, using/refreshing the cache."""
    host = host_of(base_url)
    rp = urllib.robotparser.RobotFileParser()

    cached = await repo.get_robots(host)
    if cached is not None:
        rp.parse((cached["body"] or "").splitlines())
        return rp

    parsed = urllib.parse.urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    body = ""
    try:
        r = await client.get(robots_url, timeout=HTTP_TIMEOUT_S)
        if r.status_code == 200:
            body = r.text
        # 404, 5xx, anything else → empty body (fully allowed)
    except (httpx.HTTPError, httpx.TimeoutException):
        body = ""

    if "\x00" in body:
        # Not a robots.txt we can read: a Brotli body httpx can't decode (sent
        # despite Accept-Encoding: gzip, deflate), or binary at /robots.txt.
        # Postgres can't store NUL, and the raise left the church without an
        # artifact, so it headed every batch (fetch `partial` from 2026-10-26).
        # Disallow and don't cache: the robots-disallow artifact backs it off.
        rp.parse(["User-agent: *", "Disallow: /"])
        return rp

    await repo.upsert_robots(host, body, ROBOTS_TTL_SECONDS)
    rp.parse(body.splitlines())
    return rp
