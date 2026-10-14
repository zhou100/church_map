"""Fetch stage: HTTP GET church websites, write raw HTML to R2 + metadata to Postgres.

Per-domain politeness: 2s delay between requests to the same host. Robots.txt
is consulted via the Postgres-backed cache (24h TTL). One retry on timeout/5xx.

Idempotency:
  * (church_id, url, content_hash) is unique. Same-content fetches refresh
    verified storage metadata and preserve extraction state, except no-html.
  * R2 PUT skipped if HEAD shows the key already exists.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass

import httpx
import trafilatura
from psycopg import DataError, IntegrityError

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
CHURCH_BUDGET_S = 45.0
BATCH_BUDGET_S = 240.0

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


@dataclass
class FetchResult:
    pages_ok: int = 0
    pages_error: int = 0
    pages_skipped: int = 0

    @property
    def pages(self) -> int:
        return self.pages_ok + self.pages_error + self.pages_skipped


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
        if r.status_code == 200:
            mime = r.headers.get('content-type', '').split(';')[0].strip().lower()
            if (mime and mime not in ('text/html', 'application/xhtml+xml')) or (
                not mime and not re.search(br'<(?:!doctype\s+html|html|head|body)\b', r.content[:1024], re.I)
            ):
                return r.status_code, None, 'not-html'
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
) -> FetchResult:
    """Fetch at most max_pages; success means usable HTML stored in R2."""
    result = FetchResult()
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
        return FetchResult(pages_error=1)

    rp = await get_parser(repo, client, base)

    async def _do(url: str, kind: str) -> bytes | None:
        outcome = await _fetch_one_page(client, r2, rp, url, kind)

        # Storage step. If we have content, push to R2 (idempotent via HEAD).
        # If R2 is misconfigured or transiently fails, record this attempt as
        # a fetch error with content_hash=None so:
        #   1. The unique (church_id, url, content_hash) index does not lock
        #      out a future retry of the same body.
        #   2. churches_due_for_fetch counts only consumable stored HTML,
        #      so this attempt cannot make the church fresh for 30 days.
        # Without this, a transient R2 outage during fetch would silently
        # strand the church until manual DB cleanup.
        r2_key: str | None = None
        http_status = outcome.http_status
        fetch_error = outcome.error
        content_hash = outcome.content_hash
        if outcome.content_hash and outcome.raw_bytes:
            target_key = r2mod.r2_key_for(church_id, outcome.content_hash)
            try:
                def store():
                    if not r2.head(target_key):
                        r2.put_html(target_key, outcome.raw_bytes)
                # SDK calls have finite socket/retry limits and must not block
                # the event loop (including our wall-clock cancellation).
                await asyncio.to_thread(store)
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
        if r2_key:
            result.pages_ok += 1
        elif not outcome.robots_allowed:
            result.pages_skipped += 1
        else:
            result.pages_error += 1
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
            if result.pages >= max_pages:
                break
            if kind in links:
                await _do(links[kind], kind)
                await asyncio.sleep(PER_DOMAIN_DELAY_S)

    return result


async def run_fetch_batch(
    repo: CrawlRepository,
    r2: r2mod.R2Client,
    *,
    batch_size: int,
    fresh_days: int,
    crawl_run_id: int | None,
) -> dict:
    await repo.bound_fetch_transaction()
    targets = await repo.churches_due_for_fetch(limit=batch_size, fresh_days=fresh_days)
    # Leave no selection transaction open while doing network I/O.
    await repo.con.commit()
    counts = dict(rows_processed=0, rows_ok=0, rows_error=0, rows_skipped=0,
                  pages_ok=0, pages_error=0, pages_skipped=0,
                  targets_selected=len(targets), targets_remaining=len(targets), budget_exhausted=False)
    deadline = time.monotonic() + BATCH_BUDGET_S
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for t in targets:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                counts['budget_exhausted'] = True
                break
            try:
                async with asyncio.timeout(min(CHURCH_BUDGET_S, remaining)):
                    async with repo.con.transaction():
                        await repo.bound_fetch_transaction()
                        result = await fetch_church(
                            client, repo, r2, t['church_id'], t['website'], crawl_run_id
                        )
                        next_counts = _add_result(counts, result)
                        if crawl_run_id is not None:
                            await repo.update_run_progress(crawl_run_id, next_counts)
                # Only publish counters after this church committed.
                counts = next_counts
            except Exception as e:
                log.exception("fetch failed church=%s: %s", t["church_id"], e)
                # The church transaction rolled back, so earlier churches
                # survive and even SQL failures cannot poison the next one.
                next_counts = _add_result(counts, FetchResult(pages_error=1))
                try:
                    async with repo.con.transaction():
                        await repo.bound_fetch_transaction()
                        await repo.insert_artifact(
                            church_id=t['church_id'], url=t['website'], kind='homepage',
                            http_status=0, fetch_error=f'church-failed:{type(e).__name__}',
                            robots_allowed=True, content_hash=None, r2_key=None,
                            bytes_raw=None, bytes_text=None, crawl_run_id=crawl_run_id,
                        )
                        if crawl_run_id is not None:
                            await repo.update_run_progress(crawl_run_id, next_counts)
                except (DataError, IntegrityError):
                    # A deleted church or invalid row can also reject the
                    # diagnostic artifact. Isolate it; a connection failure,
                    # in contrast, must abort rather than pretend to persist.
                    log.warning('cannot persist failure artifact church=%s', t['church_id'], exc_info=True)
                    async with repo.con.transaction():
                        await repo.bound_fetch_transaction()
                        if crawl_run_id is not None:
                            await repo.update_run_progress(crawl_run_id, next_counts)
                counts = next_counts
        if counts['targets_remaining'] and time.monotonic() >= deadline:
            counts['budget_exhausted'] = True
    return counts


def _add_result(counts: dict, result: FetchResult) -> dict:
    out = dict(counts)
    out['rows_processed'] += 1
    out['targets_remaining'] -= 1
    # A church with some usable pages advances extract even if an optional
    # page failed. Page-level errors still make the run partial.
    if result.pages_ok:
        out['rows_ok'] += 1
    elif result.pages_error:
        out['rows_error'] += 1
    else:
        out['rows_skipped'] += 1
    for key in ('pages_ok', 'pages_error', 'pages_skipped'):
        out[key] += getattr(result, key)
    return out
