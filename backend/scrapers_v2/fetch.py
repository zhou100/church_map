"""Fetch stage: HTTP GET church websites, write raw HTML to R2 + metadata to Postgres.

Per-domain politeness: 2s delay between requests to the same host. Robots.txt
is consulted via the Postgres-backed cache (24h TTL). One retry on timeout/5xx.

Idempotency:
  * (church_id, url, content_hash) is unique. Re-fetching the same body of the
    same URL is a no-op at the DB level.
  * R2 PUT skipped if HEAD shows the key already exists.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import urllib.parse
from dataclasses import dataclass

import httpx
import trafilatura

from backend.db.repository import CrawlRepository
from backend.scrapers_v2 import r2 as r2mod
from backend.scrapers_v2.robots import get_parser

log = logging.getLogger(__name__)

USER_AGENT = "ChurchMapBot/1.0 (+https://churchmap.vercel.app)"
PER_DOMAIN_DELAY_S = 2.0
HTTP_TIMEOUT_S = 15.0
MAX_PAGE_BYTES = 2_000_000
RETRY_DELAY_S = 5.0
DEFAULT_MAX_PAGES = 4

CANDIDATE_PATHS = [
    ("about",      ["about", "about-us", "who-we-are", "our-church"]),
    ("beliefs",    ["beliefs", "what-we-believe", "statement-of-faith", "doctrine"]),
    ("ministries", ["ministries", "ministry", "groups", "community", "kids", "youth"]),
    ("services",   ["services", "service-times", "worship", "visit"]),
]

_LINK_RE = re.compile(r'href=[\'"]([^\'"#?]+)', re.I)


@dataclass
class FetchOutcome:
    url: str
    kind: str
    http_status: int
    error: str | None
    robots_allowed: bool
    text: str | None
    raw_bytes: bytes | None
    content_hash: str | None
    r2_key: str | None


def normalize_url(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        u = urllib.parse.urlparse(raw)
        if not u.netloc or " " in u.netloc or "." not in u.netloc:
            return None
        return urllib.parse.urlunparse((u.scheme, u.netloc, u.path or "/", "", "", ""))
    except Exception:
        return None


def candidate_links(html: str, base: str) -> dict[str, str]:
    found: dict[str, str] = {}
    parsed_base = urllib.parse.urlparse(base)
    for href in _LINK_RE.findall(html or ""):
        try:
            absolute = urllib.parse.urljoin(base, href)
            au = urllib.parse.urlparse(absolute)
            if au.netloc != parsed_base.netloc:
                continue
            path_lower = au.path.lower().strip("/")
            if not path_lower:
                continue
            for kind, needles in CANDIDATE_PATHS:
                if kind in found:
                    continue
                last = path_lower.rsplit("/", 1)[-1]
                if any(n == last or last.startswith(n + "-") or last.endswith("-" + n) for n in needles):
                    found[kind] = urllib.parse.urlunparse(
                        (au.scheme, au.netloc, au.path, "", "", "")
                    )
                    break
        except Exception:
            continue
    return found


def extract_clean_text(html: str) -> str:
    try:
        out = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
        return out.strip()
    except Exception:
        return ""


async def _fetch_once(client: httpx.AsyncClient, url: str) -> tuple[int, bytes | None, str | None]:
    try:
        r = await client.get(url, timeout=HTTP_TIMEOUT_S, follow_redirects=True)
        if len(r.content) > MAX_PAGE_BYTES:
            return r.status_code, None, "page-too-large"
        return r.status_code, r.content, None
    except httpx.TimeoutException:
        return 0, None, "timeout"
    except httpx.HTTPError as e:
        return 0, None, type(e).__name__


async def _fetch_with_retry(
    client: httpx.AsyncClient, url: str
) -> tuple[int, bytes | None, str | None]:
    status, body, err = await _fetch_once(client, url)
    retryable = err == "timeout" or (500 <= status < 600)
    if retryable:
        await asyncio.sleep(RETRY_DELAY_S)
        status, body, err = await _fetch_once(client, url)
    return status, body, err


async def _fetch_one_page(
    client: httpx.AsyncClient,
    r2: r2mod.R2Client,
    rp,
    url: str,
    kind: str,
) -> FetchOutcome:
    if not rp.can_fetch(USER_AGENT, url):
        return FetchOutcome(
            url=url, kind=kind, http_status=0, error="robots-disallow",
            robots_allowed=False, text=None, raw_bytes=None,
            content_hash=None, r2_key=None,
        )

    status, body, err = await _fetch_with_retry(client, url)
    if status != 200 or body is None:
        return FetchOutcome(
            url=url, kind=kind, http_status=status, error=err,
            robots_allowed=True, text=None, raw_bytes=None,
            content_hash=None, r2_key=None,
        )

    html = body.decode("utf-8", errors="replace")
    text = extract_clean_text(html)
    if not text:
        return FetchOutcome(
            url=url, kind=kind, http_status=status, error="no-text",
            robots_allowed=True, text=None, raw_bytes=body,
            content_hash=None, r2_key=None,
        )

    chash = r2mod.content_hash_of(text)
    key = r2mod.r2_key_for(0, chash)  # church_id patched in by caller
    return FetchOutcome(
        url=url, kind=kind, http_status=status, error=None,
        robots_allowed=True, text=text, raw_bytes=body,
        content_hash=chash, r2_key=key,
    )


async def fetch_church(
    client: httpx.AsyncClient,
    repo: CrawlRepository,
    r2: r2mod.R2Client,
    church_id: int,
    website: str,
    crawl_run_id: int | None,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> int:
    """Fetch homepage + up to (max_pages - 1) candidate pages. Returns artifact count."""
    base = normalize_url(website)
    if not base:
        # Record the attempt so the 48h failure backoff in churches_due_for_fetch
        # kicks in. Without this, malformed-website churches have no row in
        # raw_crawl_artifacts, last_try stays NULL forever, and every cron run
        # re-selects them and burns the batch on instant fast-fails.
        await repo.insert_artifact(
            church_id=church_id,
            url=(website or "")[:500],
            kind="homepage",
            http_status=0,
            fetch_error="bad-url",
            robots_allowed=True,
            content_hash=None,
            r2_key=None,
            bytes_raw=None,
            bytes_text=None,
            crawl_run_id=crawl_run_id,
        )
        return 0

    rp = await get_parser(repo, client, base)
    written = 0

    async def _do(url: str, kind: str) -> bytes | None:
        nonlocal written
        outcome = await _fetch_one_page(client, r2, rp, url, kind)

        # Storage step. If we have content, push to R2 (idempotent via HEAD).
        # If R2 is misconfigured or transiently fails, record this attempt as
        # a fetch error with content_hash=None so:
        #   1. The unique (church_id, url, content_hash) index does not lock
        #      out a future retry of the same body.
        #   2. churches_due_for_fetch (which only counts http_status=200) does
        #      not treat the church as "fresh" for 30 days.
        # Without this, a transient R2 outage during fetch would silently
        # strand the church until manual DB cleanup.
        r2_key: str | None = None
        http_status = outcome.http_status
        fetch_error = outcome.error
        content_hash = outcome.content_hash
        if outcome.content_hash and outcome.raw_bytes:
            target_key = r2mod.r2_key_for(church_id, outcome.content_hash)
            try:
                if not r2.head(target_key):
                    r2.put_html(target_key, outcome.raw_bytes)
                r2_key = target_key
            except r2mod.R2Error as e:
                log.warning("R2 PUT failed for church=%s url=%s: %s", church_id, url, e)
                # Demote: don't record a "fresh" 200 artifact we can't extract.
                http_status = 0
                fetch_error = f"r2-failed:{type(e).__name__}"
                content_hash = None
                r2_key = None

        await repo.insert_artifact(
            church_id=church_id,
            url=outcome.url,
            kind=outcome.kind,
            http_status=http_status,
            fetch_error=fetch_error,
            robots_allowed=outcome.robots_allowed,
            content_hash=content_hash,
            r2_key=r2_key,
            bytes_raw=len(outcome.raw_bytes) if outcome.raw_bytes else None,
            bytes_text=len(outcome.text) if outcome.text else None,
            crawl_run_id=crawl_run_id,
        )
        written += 1
        return outcome.raw_bytes if r2_key else None

    home_body = await _do(base, "homepage")
    await asyncio.sleep(PER_DOMAIN_DELAY_S)

    if home_body and max_pages > 1:
        try:
            html = home_body.decode("utf-8", errors="replace")
            links = candidate_links(html, base)
        except Exception:
            links = {}
        for kind in ("about", "beliefs", "ministries", "services"):
            if written >= max_pages:
                break
            if kind in links:
                await _do(links[kind], kind)
                await asyncio.sleep(PER_DOMAIN_DELAY_S)

    return written


async def run_fetch_batch(
    repo: CrawlRepository,
    r2: r2mod.R2Client,
    *,
    batch_size: int,
    fresh_days: int,
    crawl_run_id: int | None,
) -> dict:
    targets = await repo.churches_due_for_fetch(limit=batch_size, fresh_days=fresh_days)
    rows_processed = 0
    rows_ok = 0
    rows_error = 0
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for t in targets:
            rows_processed += 1
            try:
                await fetch_church(
                    client, repo, r2, t["church_id"], t["website"], crawl_run_id
                )
                rows_ok += 1
            except Exception as e:
                log.exception("fetch failed church=%s: %s", t["church_id"], e)
                rows_error += 1
    return {"rows_processed": rows_processed, "rows_ok": rows_ok, "rows_error": rows_error}
