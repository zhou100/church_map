"""Polite per-church website fetcher.

For each church with a website URL: respect robots.txt, fetch the homepage
plus a small set of best-guess pages (about/beliefs/ministries), extract
clean text via trafilatura, and cache rows in the website_pages table.

Per-domain rate-limited, single-host concurrency = 1 (we typically only hit
one host per church anyway).

Designed to be re-runnable: pages with status_code 200 within FRESH_DAYS
are skipped on subsequent runs.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import httpx
import trafilatura

log = logging.getLogger(__name__)

USER_AGENT = "ChurchMapBot/1.0 (+https://churchmap.vercel.app)"
PER_DOMAIN_DELAY_S = 2.0
HTTP_TIMEOUT_S = 15.0
MAX_PAGE_BYTES = 2_000_000
FRESH_DAYS = 30

CANDIDATE_PATHS = [
    ("about",      ["about", "about-us", "who-we-are", "our-church"]),
    ("beliefs",    ["beliefs", "what-we-believe", "statement-of-faith", "doctrine"]),
    ("ministries", ["ministries", "ministry", "groups", "community", "kids", "youth"]),
    ("services",   ["services", "service-times", "worship", "visit"]),
]

_LINK_RE = re.compile(r'href=[\'"]([^\'"#?]+)', re.I)


@dataclass
class FetchResult:
    url: str
    kind: str
    status_code: int
    text: str | None
    error: str | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_url(raw: str) -> str | None:
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


def _robots(client: httpx.Client, base: str) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    parsed = urllib.parse.urlparse(base)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        r = client.get(robots_url, timeout=HTTP_TIMEOUT_S)
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
        else:
            rp.parse([])
    except Exception:
        rp.parse([])
    return rp


def _candidate_links(html: str, base: str) -> dict[str, str]:
    """Pick best-guess links for known kinds. One URL per kind, max."""
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
                    found[kind] = urllib.parse.urlunparse((au.scheme, au.netloc, au.path, "", "", ""))
                    break
        except Exception:
            continue
    return found


def _fetch_one(client: httpx.Client, url: str) -> tuple[int, str | None, str | None]:
    try:
        r = client.get(url, timeout=HTTP_TIMEOUT_S, follow_redirects=True)
        if len(r.content) > MAX_PAGE_BYTES:
            return r.status_code, None, "page-too-large"
        return r.status_code, r.text, None
    except httpx.TimeoutException:
        return 0, None, "timeout"
    except Exception as e:
        return 0, None, type(e).__name__


def _extract_text(html: str) -> str:
    try:
        out = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
        return out.strip()
    except Exception:
        return ""


def _is_fresh(con: sqlite3.Connection, church_id: int, url: str) -> bool:
    row = con.execute(
        "SELECT fetched_at, status_code FROM website_pages WHERE church_id=? AND url=?",
        (church_id, url),
    ).fetchone()
    if not row:
        return False
    if row[1] != 200:
        return False
    try:
        fetched = datetime.fromisoformat(row[0])
        return datetime.now(timezone.utc) - fetched < timedelta(days=FRESH_DAYS)
    except Exception:
        return False


def _upsert_page(con: sqlite3.Connection, church_id: int, kind: str, fetched: FetchResult, robots_allowed: bool) -> None:
    text = fetched.text or ""
    chash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
    con.execute(
        """
        INSERT INTO website_pages
          (church_id, url, kind, status_code, fetched_at, robots_allowed, content_hash, text, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(church_id, url) DO UPDATE SET
          kind=excluded.kind,
          status_code=excluded.status_code,
          fetched_at=excluded.fetched_at,
          robots_allowed=excluded.robots_allowed,
          content_hash=excluded.content_hash,
          text=excluded.text,
          error=excluded.error
        """,
        (
            church_id, fetched.url, kind, fetched.status_code, _now_iso(),
            1 if robots_allowed else 0, chash, text, fetched.error,
        ),
    )


def fetch_church(con: sqlite3.Connection, church_id: int, website: str, *, max_pages: int = 4) -> list[FetchResult]:
    """Fetch homepage + up to (max_pages - 1) candidate pages for one church."""
    base = _normalize_url(website)
    if not base:
        return []

    results: list[FetchResult] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        rp = _robots(client, base)

        def _do(url: str, kind: str) -> FetchResult:
            allowed = rp.can_fetch(USER_AGENT, url)
            if not allowed:
                fr = FetchResult(url=url, kind=kind, status_code=0, text=None, error="robots-disallow")
                _upsert_page(con, church_id, kind, fr, robots_allowed=False)
                con.commit()
                return fr
            if _is_fresh(con, church_id, url):
                row = con.execute(
                    "SELECT status_code, text, error FROM website_pages WHERE church_id=? AND url=?",
                    (church_id, url),
                ).fetchone()
                return FetchResult(url=url, kind=kind, status_code=row[0], text=row[1], error=row[2])
            time.sleep(PER_DOMAIN_DELAY_S)
            status, html, err = _fetch_one(client, url)
            text = _extract_text(html or "") if html else ""
            fr = FetchResult(url=url, kind=kind, status_code=status, text=text or None, error=err)
            _upsert_page(con, church_id, kind, fr, robots_allowed=True)
            con.commit()
            return fr

        home = _do(base, "homepage")
        results.append(home)
        if home.status_code == 200 and home.text and max_pages > 1:
            # Re-fetch raw HTML for link discovery (trafilatura strips it).
            try:
                r = client.get(base, timeout=HTTP_TIMEOUT_S, follow_redirects=True)
                links = _candidate_links(r.text, base)
            except Exception:
                links = {}
            for kind in ("about", "beliefs", "ministries", "services"):
                if len(results) >= max_pages:
                    break
                if kind in links:
                    results.append(_do(links[kind], kind))
    return results


def iter_targets(con: sqlite3.Connection, where: str = "", params: Iterable = ()) -> list[tuple[int, str]]:
    sql = "SELECT church_id, website FROM Churches WHERE website IS NOT NULL AND website != ''"
    if where:
        sql += f" AND {where}"
    return [(r[0], r[1]) for r in con.execute(sql, tuple(params)).fetchall()]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    con = sqlite3.connect("holyhub.db")
    targets = iter_targets(con)
    print(f"Total churches with website: {len(targets)}")
