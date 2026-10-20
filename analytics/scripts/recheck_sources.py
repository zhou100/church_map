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
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import lxml.html

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fact_fingerprint import fact_fingerprint, source_of  # noqa: E402

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
BLOCK_TAGS = ("p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3", "h4", "h5",
              "h6", "section", "article", "header", "footer", "nav", "aside", "address", "blockquote", "dd",
              "dt", "pre", "figcaption", "option")  # block-level only: inline tags can split a word
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
        v2_candidate = "excerpt" in r and "source_url" in r
        for g in (("candidate",) if v2_candidate else GROUPS):
            url, ex = source_of(r, g)
            stype = r.get("source_type", "") if v2_candidate else r.get(f"{g}_source_type", "")
            if url and ex:
                out.append({"row_key": key, "name": name, "group": g, "source_type": stype,
                            "source_url": url.strip(), "excerpt": ex,
                            "fact_fingerprint": fact_fingerprint(r, g)})
    return out


# ---------------------------------------------------------------- matching

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}))
    s = re.sub(r"[\u200b-\u200d\u2060\ufeff]", "", s)  # zero-width characters in page markup
    s = re.sub(r"[#*_`]", " ", s)  # markdown left over from the agent's text extraction
    return re.sub(r"\s+", " ", s).strip()


def loose(s: str) -> str:
    """Letters and digits only (any script), no spaces: survives words split by markup."""
    return "".join(ch for ch in norm(s) if ch.isalnum())


def spaced(s: str) -> str:
    """Letters and digits (any script) as space-separated runs: punctuation, table
    borders and line breaks drop out, but numbers and words keep their boundaries."""
    out = " ".join(re.findall(r"[^\W_]+", norm(s)))
    # "11:15am" and "11:15 am", "下午1:30" and "下午 1:30" compare equal.
    return re.sub(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)", " ", out)


MIN_FRAGMENT = 6     # letters/digits; shorter fragments get stricter matching, never dropped
NEAR_CHARS = 300     # a short fragment must sit this close to the fragment before it


def segments(excerpt: str, fine: bool = False) -> list[str]:
    """Split an excerpt joined from several page fragments. Nothing is discarded:
    dropping a short fragment would let "Sunday worship / 9 am" verify against a
    page that says "Sunday worship at 11 am"."""
    parts = [p.strip() for p in SEGMENT_SPLIT.split(excerpt) if p and p.strip()]
    if fine:
        parts = [q.strip() for p in parts for q in FRAGMENT_SPLIT.split(p) if q and q.strip()]
    return parts or [excerpt]


def _bounded_positions(hay: str, needle: str) -> list[int]:
    """Start positions where needle occurs without splitting a number or a Latin word:
    "23 Main" is not in "123 Main", "9402" is not in "94024", "am" is not in "amen"."""
    out, start = [], hay.find(needle) if needle else -1
    while start != -1:
        end = start + len(needle)
        before = hay[start - 1] if start > 0 else ""
        after = hay[end] if end < len(hay) else ""
        ok_before = not (needle[0].isascii() and needle[0].isalnum() and before.isascii() and before.isalnum())
        ok_after = not (needle[-1].isascii() and needle[-1].isalnum() and after.isascii() and after.isalnum())
        if ok_before and ok_after:
            out.append(start)
        start = hay.find(needle, start + 1)
    return out


EXCERPT_CAP = 200  # brief: excerpts are at most 200 characters, so the agent may cut one mid-word


def _trim_cut_words(ss: str) -> str:
    """Drop an alphabetic word cut off by the 200-character cap at either end.
    Numbers are never trimmed: a cut number would match a different one."""
    words = ss.split()
    if len(words) > 3 and words[-1].isalpha():
        words = words[:-1]
    if len(words) > 3 and words[0].isalpha():
        words = words[1:]
    return " ".join(words)


def squash(s: str) -> str:
    """Spaceless text for words split by markup or PDF layout ("Sun day" -> "sunday"),
    except that a space between two numbers stays: "5528 1430" must not become one
    number. Built from spaced(), so punctuation is already gone."""
    return re.sub(r"(?<!\d) | (?!\d)", "", spaced(s))


def _digit_bounded_at(hay: str, needle: str) -> bool:
    """needle occurs in hay at a position where it doesn't extend a number on either
    side. The boundary belongs to the same occurrence: "23 Main" inside "123 Main" is
    rejected even if a separate "23" ("Established 23 years ago") is elsewhere."""
    start = hay.find(needle) if needle else -1
    while start != -1:
        end = start + len(needle)
        if not (needle[0].isdigit() and start and hay[start - 1].isdigit()) and \
           not (needle[-1].isdigit() and end < len(hay) and hay[end].isdigit()):
            return True
        start = hay.find(needle, start + 1)
    return False


def _score(segs: list[str], page_s: str, page_q: str, capped: bool = False) -> tuple[int, set]:
    found, modes, last = 0, set(), None
    for i, seg in enumerate(segs):
        ss = spaced(seg)
        positions = _bounded_positions(page_s, ss)
        if not positions and capped and i in (0, len(segs) - 1):
            positions = _bounded_positions(page_s, _trim_cut_words(ss))
        short = len(loose(seg)) < MIN_FRAGMENT
        if short and last is not None:
            # A short fragment ("9 am", "94022") must also sit near the previous fragment.
            positions = [p for p in positions if abs(p - last) <= NEAR_CHARS]
        if positions:
            found, last = found + 1, positions[0]
            modes.add("exact")
        elif not short and len(segments(seg, fine=True)) == 1 and _digit_bounded_at(page_q, squash(seg)):
            # Spaceless matching (PDF text, words split by markup) for an indivisible
            # fragment, with number boundaries checked at that very occurrence.
            found, last = found + 1, None
            modes.add("loose")
    return found, modes


def match(excerpt: str, page_text: str) -> tuple[str, int, int, str]:
    """Whole excerpt first, then its fragments, then finer fragments.

    Every part of the excerpt has to be found. Numbers and Latin words match whole;
    short fragments must also appear near the fragment before them.
    """
    page_s, page_q = spaced(page_text), squash(page_text)
    best = None
    capped = len(excerpt) >= EXCERPT_CAP - 10
    for segs in ([excerpt], segments(excerpt), segments(excerpt, fine=True)):
        found, modes = _score(segs, page_s, page_q, capped)
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
        # text_content() glues adjacent blocks ("worship</p><p>9 am" -> "worship9 am");
        # a line break after each block keeps words and numbers apart.
        for el in doc.iter(*BLOCK_TAGS):
            el.tail = "\n" + (el.tail or "")
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
            self.robots[base] = await self._load_robots(base + "/robots.txt")
        return self.robots[base]

    async def _load_robots(self, robots_url: str) -> RobotFileParser:
        """RFC 9309: follow up to 5 redirects (each hop safety-checked); 4xx means no
        robots file (allow); 5xx, network errors, unsafe hops or too many redirects mean
        unreachable (disallow). Never treat a redirect as "no robots file"."""
        rp = RobotFileParser()
        hop = robots_url
        for _ in range(MAX_REDIRECTS + 1):
            ph = urlparse(hop)
            if ph.scheme not in ("http", "https") or not ph.hostname \
                    or not await asyncio.to_thread(is_public, ph.hostname):
                rp.disallow_all = True
                return rp
            try:
                r = await self._polite_get(hop)
            except httpx.HTTPError:
                rp.disallow_all = True
                return rp
            if r.is_redirect and r.headers.get("location"):
                hop = urljoin(hop, r.headers["location"])
                continue
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            elif 400 <= r.status_code < 500:
                rp.parse([])
            else:
                rp.disallow_all = True
            return rp
        rp.disallow_all = True
        return rp

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
            "segments_found", "segments_total", "match_mode", "note", "checked_at", "fact_fingerprint", "excerpt"]
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
        append_history(path.stem, out)
        print(f"\n{path.name}: {len(out)} facts -> {dest.relative_to(ROOT)}")
        for v, n in Counter(r["verdict"] for r in out).most_common():
            print(f"  {v:18} {n}")


HISTORY_COLS = ["row_key", "group", "source_url", "verdict", "http_status", "fact_fingerprint", "checked_at"]


def append_history(stem: str, rows: list[dict]) -> None:
    """Append every verdict to returns/recheck/history/<stem>.csv (no excerpts). The
    latest file above is what the seeds use; the history lets a fact keep a recent
    "verified" through a transient fetch failure (see build_seeds.carry_over)."""
    hist = OUT_DIR / "history" / f"{stem}.csv"
    hist.parent.mkdir(parents=True, exist_ok=True)
    new = not hist.exists()
    with hist.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_COLS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def main() -> None:
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # malformed bulletin PDFs are common and harmless
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", type=Path)
    asyncio.run(run(ap.parse_args().files))


if __name__ == "__main__":
    main()
