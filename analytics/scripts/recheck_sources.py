"""Re-verify Muse excerpts against the pages they cite.

This is the control that replaced further human audit (plan §6, "Compensating
controls"). For every fact group with a non-Facebook source, it fetches the
cited URL and checks that the verbatim excerpt is on that page. A fact whose
excerpt cannot be found is not promoted.

    analytics/.venv/bin/python analytics/scripts/recheck_sources.py \
        muse_handoff/returns/results_current.csv muse_handoff/returns/new_candidates_CN.csv

Writes muse_handoff/returns/recheck/<input stem>.csv (gitignored: it repeats
excerpts) and prints a summary per file.

Fetching follows the production crawler's manners: the ChurchMapBot user agent,
robots.txt, and one request at a time per host with a 2 s delay. URLs come from
an external agent, so each hop (including redirects) must resolve to a public
address. Facebook and Instagram are never fetched (D-3: Page facts are checked
by the next Muse pass, not by our crawler).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import ipaddress
import logging
import re
import socket
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import lxml.html

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "muse_handoff" / "returns" / "recheck"

USER_AGENT = "ChurchMapBot/1.0 (+https://churchmap.vercel.app)"
PER_HOST_DELAY_S = 2.0
TIMEOUT_S = 20.0
MAX_BYTES = 15 * 1024 * 1024
MAX_REDIRECTS = 5
HOST_CONCURRENCY = 6
NEVER_FETCH = ("facebook.com", "fb.com", "instagram.com", "fbcdn.net")

GROUPS = ("status", "address", "phone", "service", "kids")
SEGMENT_SPLIT = re.compile(r"\s+(?:\.\.\.|…|/|\|)\s+|…|\s\.\.\.\s?")
# Second pass: fragments joined with dashes, semicolons or "+" (common in the agent's excerpts).
FRAGMENT_SPLIT = re.compile(r"\s+[—–+·]\s+|\s*[;；]\s+|\s\|\s")
# An "excerpt" that describes the page instead of quoting it (seen in task CN status fields).
DESCRIPTION_RE = re.compile(r"\b(homepage carries|site footer|own-site date|images? dated|no dated content|"
                            r"current-date content|fetched page|within 12 months|fellowship post)\b", re.I)


# ---------------------------------------------------------------- inputs

def fact_rows(path: Path) -> list[dict]:
    """One dict per (row, fact group) that has a source URL and an excerpt."""
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for i, r in enumerate(rows, 1):
        key = r.get("church_id") or r.get("candidate_ref") or f"row{i}"
        name = r.get("current_name") or r.get("candidate_name") or ""
        if "excerpt" in r and "source_url" in r:  # v2 candidate: one source for the row
            groups = [("candidate", r["source_url"], r.get("source_type", ""), r["excerpt"])]
        else:
            groups = [(g, r.get(f"{g}_source_url", ""), r.get(f"{g}_source_type", ""), r.get(f"{g}_excerpt", ""))
                      for g in GROUPS]
        for g, url, stype, ex in groups:
            if url and ex:
                out.append({"row_key": key, "name": name, "group": g, "source_type": stype,
                            "source_url": url.strip(), "excerpt": ex})
    return out


# ---------------------------------------------------------------- matching

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}))
    s = re.sub(r"[\u200b-\u200d\u2060\ufeff]", "", s)  # zero-width characters in page markup
    s = re.sub(r"[#*_`]", " ", s)  # markdown left over from the agent's text extraction
    return re.sub(r"\s+", " ", s).strip()


def loose(s: str) -> str:
    """Letters and digits only (any script): survives line breaks, tables, punctuation."""
    return "".join(ch for ch in norm(s) if ch.isalnum())


def segments(excerpt: str, fine: bool = False) -> list[str]:
    parts = [p.strip() for p in SEGMENT_SPLIT.split(excerpt) if p and p.strip()]
    if fine:
        parts = [q.strip() for p in parts for q in FRAGMENT_SPLIT.split(p) if q and q.strip()]
    keep = [p for p in parts if len(loose(p)) >= 6]
    return keep or [excerpt]


def _score(segs: list[str], page_n: str, page_l: str) -> tuple[int, set]:
    found, modes = 0, set()
    for seg in segs:
        if norm(seg) in page_n:
            found += 1
            modes.add("exact")
        elif loose(seg) and loose(seg) in page_l:
            found += 1
            modes.add("loose")
    return found, modes


def match(excerpt: str, page_text: str) -> tuple[str, int, int, str]:
    """Whole excerpt first, then its fragments, then finer fragments.

    A fragment needs >= 6 letters/digits, so splitting can't verify an excerpt
    from trivially common words.
    """
    page_n, page_l = norm(page_text), loose(page_text)
    best = None
    for segs in ([excerpt], segments(excerpt), segments(excerpt, fine=True)):
        found, modes = _score(segs, page_n, page_l)
        cand = (found / len(segs), found, len(segs), modes)
        if best is None or cand[0] > best[0]:
            best = cand
        if found == len(segs):
            break
    _, found, total, modes = best
    verdict = "verified" if found == total else "partial" if found else "not_found"
    mode = "exact" if modes == {"exact"} else "loose" if modes else ""
    if verdict != "verified" and DESCRIPTION_RE.search(excerpt):
        verdict = "not_an_excerpt"
    return verdict, found, total, mode


# ---------------------------------------------------------------- fetching

def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def parse_html(content: bytes, ctype: str):
    """Decode before parsing: lxml guesses Latin-1 for undeclared bytes, which garbles CJK."""
    m = re.search(r"charset=([\w-]+)", ctype)
    meta = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", content[:4096], re.I)
    for enc in [m.group(1) if m else None, meta.group(1).decode() if meta else None, "utf-8", "cp1252"]:
        if not enc:
            continue
        try:
            text = content.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    try:
        return lxml.html.fromstring(text)
    except ValueError:  # str input with an XML encoding declaration
        return lxml.html.fromstring(content)


def page_text(content: bytes, ctype: str, url: str) -> str | None:
    ctype = ctype.lower()
    if "pdf" in ctype or urlparse(url).path.lower().endswith(".pdf") or content[:5] == b"%PDF-":
        from pypdf import PdfReader  # analytics venv only; keeps the module importable in CI

        reader = PdfReader(io.BytesIO(content))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if "html" in ctype or "xml" in ctype or ctype.startswith("text/") or not ctype:
        doc = parse_html(content, ctype)
        for bad in doc.xpath("//script|//style|//noscript|//template"):
            bad.drop_tree()
        attrs = " ".join(doc.xpath("//meta[@name='description']/@content|//img/@alt|//@title"))
        return doc.text_content() + "\n" + attrs
    return None


class Fetcher:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.robots: dict[str, RobotFileParser] = {}
        self.host_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.last_hit: dict[str, float] = {}
        self.sem = asyncio.Semaphore(HOST_CONCURRENCY)

    async def _polite_get(self, url: str) -> httpx.Response:
        host = host_of(url)
        async with self.host_locks[host]:
            wait = PER_HOST_DELAY_S - (time.monotonic() - self.last_hit.get(host, 0))
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await self.client.get(url, timeout=TIMEOUT_S, follow_redirects=False)
            finally:
                self.last_hit[host] = time.monotonic()

    async def _robots(self, url: str) -> RobotFileParser:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.robots:
            rp = RobotFileParser()
            try:
                r = await self._polite_get(base + "/robots.txt")
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])  # same as the crawler: an unreachable robots.txt means allow
            self.robots[base] = rp
        return self.robots[base]

    async def fetch(self, url: str) -> dict:
        async with self.sem:
            hop = url
            for _ in range(MAX_REDIRECTS + 1):
                p = urlparse(hop)
                if p.scheme not in ("http", "https") or not p.hostname:
                    return {"verdict": "unsafe_url", "note": "not an http(s) URL", "final_url": hop}
                if any(h in p.hostname.lower() for h in NEVER_FETCH):
                    return {"verdict": "skipped_facebook", "note": "redirects to a never-fetch host", "final_url": hop}
                if not await asyncio.to_thread(is_public, p.hostname):
                    return {"verdict": "unsafe_url", "note": "host does not resolve to a public address", "final_url": hop}
                if not (await self._robots(hop)).can_fetch(USER_AGENT, hop):
                    return {"verdict": "robots_blocked", "final_url": hop}
                try:
                    r = await self._polite_get(hop)
                except httpx.HTTPError as e:
                    return {"verdict": "fetch_failed", "note": type(e).__name__, "final_url": hop}
                if r.is_redirect and r.headers.get("location"):
                    hop = urljoin(hop, r.headers["location"])
                    continue
                if r.status_code != 200:
                    return {"verdict": "fetch_failed", "http_status": r.status_code, "final_url": hop}
                if len(r.content) > MAX_BYTES:
                    return {"verdict": "unsupported", "note": "too large", "http_status": 200, "final_url": hop}
                try:
                    text = page_text(r.content, r.headers.get("content-type", ""), hop)
                except Exception as e:  # malformed PDF/HTML
                    return {"verdict": "unsupported", "note": f"parse error: {type(e).__name__}", "http_status": 200, "final_url": hop}
                if text is None:
                    return {"verdict": "unsupported", "note": r.headers.get("content-type", ""), "http_status": 200, "final_url": hop}
                return {"verdict": "fetched", "text": text, "http_status": 200, "final_url": hop}
            return {"verdict": "fetch_failed", "note": "too many redirects", "final_url": hop}


# ---------------------------------------------------------------- main

async def run(paths: list[Path]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = {p: fact_rows(p) for p in paths}
    urls = {j["source_url"] for js in jobs.values() for j in js
            if j["source_type"] != "fb_page" and not any(h in host_of(j["source_url"]) for h in NEVER_FETCH)}
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        f = Fetcher(client)
        ordered = sorted(urls)  # zip against the same order the fetches were issued in
        results = dict(zip(ordered, await asyncio.gather(*(f.fetch(u) for u in ordered))))
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cols = ["row_key", "name", "group", "source_type", "source_url", "final_url", "http_status", "verdict",
            "segments_found", "segments_total", "match_mode", "note", "checked_at", "excerpt"]
    for path, js in jobs.items():
        out = []
        for j in js:
            row = {**j, "checked_at": checked_at, "final_url": "", "http_status": "", "note": "",
                   "segments_found": "", "segments_total": "", "match_mode": ""}
            if j["source_type"] == "fb_page" or any(h in host_of(j["source_url"]) for h in NEVER_FETCH):
                row["verdict"] = "skipped_facebook"
            else:
                res = results[j["source_url"]]
                row.update(final_url=res.get("final_url", ""), http_status=res.get("http_status", ""), note=res.get("note", ""))
                if res["verdict"] == "fetched":
                    v, found, total, mode = match(j["excerpt"], res["text"])
                    row.update(verdict=v, segments_found=found, segments_total=total, match_mode=mode)
                else:
                    row["verdict"] = res["verdict"]
            out.append(row)
        dest = OUT_DIR / f"{path.stem}.csv"
        with dest.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(out)
        print(f"\n{path.name}: {len(out)} facts -> {dest.relative_to(ROOT)}")
        for v, n in Counter(r["verdict"] for r in out).most_common():
            print(f"  {v:18} {n}")


def main() -> None:
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # malformed bulletin PDFs are common and harmless
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", type=Path)
    asyncio.run(run(ap.parse_args().files))


if __name__ == "__main__":
    main()
