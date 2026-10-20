"""Repair excerpts that failed re-verification, from the cited page itself.

When a fact (address, phone, service times) is on the cited page but the agent's
excerpt is not (paraphrased, stitched, truncated), replace the excerpt with a
verbatim passage of that page that contains the fact. Nothing else changes: not
the fact, not the source URL. A fact that is not on its cited page stays as it
is and keeps failing the check.

    analytics/.venv/bin/python analytics/scripts/repair_excerpts.py muse_handoff/returns/results_C.csv

--resource-blocked: for a fact whose cited page we can't fetch (403, robots.txt),
look for the same fact on the church's own website (homepage + up to 3 contact/
schedule links) and cite that page instead if it is there.

--manual applies hand-written corrections (row_key, column, old_value, new_value,
reason) first, e.g. a city the agent changed because our ZIP table was incomplete.

Reads returns/recheck/<stem>.csv for the failing facts, keeps the agent's file as
<stem>.muse.csv (first run only), rewrites <stem>.csv with the repairs (runs
accumulate; re-check between runs), and appends every change, with a run_id, to
returns/repairs/<stem>.csv (history is never overwritten). Re-run
recheck_sources.py afterwards: the repaired excerpts must verify like any other.

A repaired excerpt is not a publish decision: it only proves the page states the
fact. Addresses must state the full street (house number + every street word).

Fetching uses recheck_sources.Fetcher (robots.txt, public hosts, 2 s per host, no
Facebook).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "muse_handoff"))
import recheck_sources as rs  # noqa: E402
from validate_returns import (NAME_ABBREV, STREET_DIRECTION, STREET_SUFFIX,  # noqa: E402
                              excerpt_supports_service, excerpt_supports_street, service_times_of,
                              street_key)

EXCERPT_CAP = 200
REPAIRABLE = ("not_found", "partial", "not_an_excerpt")
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m\b\.?", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PERSON_CUE_RE = re.compile(r"\b(Contact|Pastor|Rev\.?|Reverend|Father|Fr\.|Deacon|Elder|Bishop|Msgr\.?)\b")


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


def window(text: str, start: int, end: int) -> str | None:
    """Verbatim passage covering [start, end) with a little context, cut at word
    edges, at most 200 characters."""
    if end - start > EXCERPT_CAP:
        return None
    a = max(0, start - 40)
    b = min(len(text), max(end, a + EXCERPT_CAP))
    if b - a > EXCERPT_CAP:
        b = a + EXCERPT_CAP
    if b < end:
        a, b = end - EXCERPT_CAP, end
    if a > 0 and text[a - 1] != " ":  # don't start mid-word
        nxt = text.find(" ", a)
        a = nxt + 1 if 0 <= nxt < start else a
    if b < len(text) and text[b] != " ":  # don't end mid-word
        prev = text.rfind(" ", end, b)
        b = prev if prev >= end else b
    # Keep e-mail addresses out (rule N1): cut the passage at the nearest one on
    # either side of the fact instead of rewriting the page text.
    for m in EMAIL_RE.finditer(text, a, b):
        if m.end() <= start:
            a = max(a, m.end())
        elif m.start() >= end:
            b = min(b, m.start())
        else:
            return None  # the fact itself sits inside an e-mail address
    # Keep people out too (rule N1): a clergy/contact cue near the fact usually comes
    # with a name ("Contact Sam Shin | Senior Pastor"). Cut the passage before the cue
    # and the capitalized words leading into it; drop leading context that has one.
    for m in PERSON_CUE_RE.finditer(text, a, b):
        if m.start() >= end:
            lead = re.search(r"(?:\b[A-Z][\w.'-]*[\s|,]+){0,3}$", text[end:m.start()])
            b = min(b, end + (lead.start() if lead else m.start() - end))
        elif m.end() <= start:
            a = start
    snippet = text[a:b].strip()
    return snippet if snippet and len(snippet) <= EXCERPT_CAP else None


def _token_pattern(tok: str) -> str:
    """Every spelling that normalizes to this token: 'rd' -> (road|rd), 'w' -> (west|w)."""
    forms = {k for k, v in {**STREET_SUFFIX, **STREET_DIRECTION, **NAME_ABBREV}.items() if v == tok} | {tok}
    alts = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    if tok.isdigit():
        return rf"{re.escape(tok)}(?:st|nd|rd|th)?"  # "39" matches "39th"
    return "(?:" + alts + r")\.?"


def find_address(text: str, street: str) -> str | None:
    """A passage stating this exact address: the house number followed by every word
    of the street name (suffix and direction in any spelling). "107 San Mateo Avenue"
    is not evidence for "107 San Pedro Road"."""
    key = street_key(street)
    if not key:
        return None
    number, name = key
    pat = re.compile(rf"(?<!\d){re.escape(number)}\W+" + r"\W+".join(_token_pattern(t) for t in name) + r"(?![\w])",
                     re.I)
    hit = pat.search(text)
    if not hit:
        return None
    passage = window(text, hit.start(), hit.end())  # window adds the context
    return passage if passage and excerpt_supports_street(passage, street) else None


def find_phone(text: str, phone: str) -> str | None:
    d = re.sub(r"\D", "", phone)[-10:]
    if len(d) != 10:
        return None
    pat = re.compile(rf"(?<!\d)\(?{d[:3]}\)?[\s.\-/]*{d[3:6]}[\s.\-/]*{d[6:]}(?!\d)")
    hit = pat.search(text)
    return window(text, hit.start(), hit.end()) if hit else None


def _times(s: str) -> list[str]:
    return [f"{int(h) % 12 + (12 if ap.lower() == 'p' else 0):02d}:{int(m or 0):02d}" for h, m, ap in TIME_RE.findall(s)]


def find_service(text: str, verbatim: str) -> str | None:
    """A passage containing the recorded schedule itself (service_times_verbatim),
    word for word up to punctuation and spacing. Matching times alone is not enough:
    "Sunday worship 10 AM" must not be repaired with a page that says "Saturday Bible
    study 10 AM; Sunday worship 11 AM". If the schedule isn't on the page as recorded,
    nothing is repaired and the fact stays for review."""
    words = re.findall(r"[^\W_]+", verbatim or "")
    if len(words) < 2 or not service_times_of(verbatim):
        return None
    pat = re.compile(r"(?<![^\W_])" + r"[\W_]*".join(re.escape(w) for w in words) + r"(?![^\W_])", re.I)
    hit = pat.search(text)
    if not hit:
        return None
    passage = window(text, hit.start(), hit.end())
    return passage if passage and excerpt_supports_service(passage, verbatim) else None


FINDERS = {
    "address": lambda text, row: find_address(text, row.get("street_address", "")),
    "phone": lambda text, row: find_phone(text, row.get("phone", "")),
    "service": lambda text, row: find_service(text, row.get("service_times_verbatim", "")),
}


UNREACHABLE = ("fetch_failed", "robots_blocked")
LINK_HINTS = re.compile(r"contact|visit|mass|schedule|service|worship|about|location|times|horario|misa", re.I)


async def official_pages(fetcher, official_url: str) -> list[tuple[str, str]]:
    """The church's own homepage plus up to 3 same-site links that look like
    contact/visit/schedule pages: (url, collapsed text). Uses the same polite,
    robots-aware fetcher as the re-check."""
    import lxml.html
    from urllib.parse import urljoin, urlparse

    home = await fetcher.fetch(official_url)
    if home["verdict"] != "fetched":
        return []
    out = [(home["final_url"], collapse(home["text"]))]
    try:
        r = await fetcher._polite_get(home["final_url"])
        doc = lxml.html.fromstring(r.content)
        host = urlparse(home["final_url"]).hostname
        links = []
        for a in doc.xpath("//a[@href]"):
            href = urljoin(home["final_url"], a.get("href"))
            if urlparse(href).hostname == host and LINK_HINTS.search(href + " " + (a.text_content() or "")):
                if href not in links and href != home["final_url"]:
                    links.append(href.split("#")[0])
    except Exception:
        links = []
    for href in links[:3]:
        page = await fetcher.fetch(href)
        if page["verdict"] == "fetched":
            out.append((page["final_url"], collapse(page["text"])))
    return out


async def resource_blocked(rows: list[dict], key_col: str, report: list[dict], log: list[dict], today: str) -> None:
    """When the cited source can't be fetched by us (403, robots), look for the same
    fact on the church's own website. If found, cite that page instead (own_site) with
    a verbatim passage. The fact value never changes; if it isn't there, nothing does."""
    by_key = {r[key_col]: r for r in rows}
    targets = [c for c in report if c["verdict"] in UNREACHABLE and c["group"] in FINDERS]
    need = {}
    for c in targets:
        row = by_key.get(c["row_key"])
        off = (row or {}).get("official_url", "")
        if row and off and urlparse_host(off) != urlparse_host(c["source_url"]):
            need.setdefault(off, []).append((c, row))
    if not need:
        return
    async with httpx.AsyncClient(headers={"User-Agent": rs.USER_AGENT}) as client:
        fetcher = rs.Fetcher(client)
        for off, items in need.items():
            pages = await official_pages(fetcher, off)
            for c, row in items:
                g = c["group"]
                for url, text in pages:
                    new = FINDERS[g](text, row)
                    if new:
                        log.append({"row_key": c["row_key"], "group": g, "action": "resourced",
                                    "reason": f"{c['verdict']} at {urlparse_host(c['source_url'])}",
                                    "old_excerpt": f"{row[f'{g}_source_url']} | {row[f'{g}_excerpt']}",
                                    "new_excerpt": f"{url} | {new}"})
                        row[f"{g}_source_url"], row[f"{g}_source_type"], row[f"{g}_excerpt"] = url, "own_site", new
                        row["notes"] = (f"{row.get('notes', '')} [ChurchMap {today}: {g} re-sourced to the church's own "
                                        f"site; the cited {urlparse_host(c['source_url'])} page blocks our checker]").strip()
                        break
                else:
                    log.append({"row_key": c["row_key"], "group": g, "action": "not_resourced",
                                "reason": "fact not found on the church's own site", "old_excerpt": "", "new_excerpt": ""})


def urlparse_host(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def apply_manual(rows: list[dict], key_col: str, manual: Path | None, log: list[dict], today: str) -> None:
    """Hand-written corrections: a CSV of row_key, column, old_value, new_value, reason.
    Applied only when the current value equals old_value, so a stale correction is a no-op."""
    if not manual:
        return
    by_key = {r[key_col]: r for r in rows}
    for c in csv.DictReader(manual.open(encoding="utf-8")):
        row = by_key.get(c["row_key"])
        if row is None or row.get(c["column"], "") != c["old_value"]:
            log.append({"row_key": c["row_key"], "group": c["column"], "action": "manual_skipped",
                        "reason": "row or old value not found", "old_excerpt": c["old_value"], "new_excerpt": c["new_value"]})
            continue
        row[c["column"]] = c["new_value"]
        row["notes"] = f"{row.get('notes', '')} [ChurchMap {today}: {c['column']} {c['reason']}]".strip()
        log.append({"row_key": c["row_key"], "group": c["column"], "action": "manual", "reason": c["reason"],
                    "old_excerpt": c["old_value"], "new_excerpt": c["new_value"]})


LOG_FIELDS = ["run_id", "logged_at", "row_key", "group", "action", "reason", "old_excerpt", "new_excerpt"]
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def append_log(log_path: Path, log: list[dict]) -> None:
    """Append-only history: every run adds its rows under its own run_id; nothing is
    overwritten. An older log without run_id columns is kept as <name>.legacy.csv."""
    log_path.parent.mkdir(exist_ok=True)
    if log_path.exists():
        with log_path.open(encoding="utf-8") as f:
            header = next(csv.reader(f), [])
        if header and header[:2] != LOG_FIELDS[:2]:
            log_path.rename(log_path.with_suffix(".legacy.csv"))
    new = not log_path.exists()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows({**row, "run_id": RUN_ID, "logged_at": now} for row in log)


async def repair(path: Path, manual: Path | None = None, resource: bool = False) -> None:
    ret = path.parent
    report = ret / "recheck" / f"{path.stem}.csv"
    original = ret / f"{path.stem}.muse.csv"
    if not original.exists():
        shutil.copy(path, original)
    # Work on the current file so repairs accumulate across runs; the agent's file
    # stays untouched in <stem>.muse.csv. Manual corrections are no-ops once applied.
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols, rows = reader.fieldnames, list(reader)
    key_col = "church_id" if "church_id" in cols else "candidate_ref"
    report_rows = list(csv.DictReader(report.open(encoding="utf-8")))
    failing = [r for r in report_rows
               if r["verdict"] in REPAIRABLE and r["group"] in FINDERS and r["source_type"] != "fb_page"]
    by_key = {r[key_col]: r for r in rows}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log: list[dict] = []
    apply_manual(rows, key_col, manual, log, today)
    if resource:
        await resource_blocked(rows, key_col, report_rows, log, today)
    async with httpx.AsyncClient(headers={"User-Agent": rs.USER_AGENT}) as client:
        fetcher = rs.Fetcher(client)
        pages = {}
        for url in sorted({r["source_url"] for r in failing}):
            pages[url] = await fetcher.fetch(url)
    for chk in failing:
        row = by_key.get(chk["row_key"])
        page = pages[chk["source_url"]]
        if row is None or page["verdict"] != "fetched":
            continue
        text = collapse(page["text"])
        new = FINDERS[chk["group"]](text, row)
        g = chk["group"]
        if not new or new == row[f"{g}_excerpt"]:
            log.append({"row_key": chk["row_key"], "group": g, "action": "not_repaired",
                        "reason": "fact not found on the cited page" if not new else "unchanged",
                        "old_excerpt": row[f"{g}_excerpt"], "new_excerpt": ""})
            continue
        log.append({"row_key": chk["row_key"], "group": g, "action": "repaired", "reason": chk["verdict"],
                    "old_excerpt": row[f"{g}_excerpt"], "new_excerpt": new})
        row[f"{g}_excerpt"] = new
        note = f"[ChurchMap {today}: {g}_excerpt re-extracted verbatim from the cited page]"
        row["notes"] = f"{row.get('notes', '')} {note}".strip()
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    append_log(ret / "repairs" / f"{path.stem}.csv", log)
    done = sum(1 for x in log if x["action"] == "repaired")
    manual_done = sum(1 for x in log if x["action"] == "manual")
    resourced = sum(1 for x in log if x["action"] == "resourced")
    print(f"{path.name}: {len(failing)} failing facts considered, {done} excerpts repaired; "
          f"{manual_done} manual corrections applied; {resourced} facts re-sourced to the church's own site")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--manual", type=Path, help="CSV of hand-written corrections for these files")
    ap.add_argument("--resource-blocked", action="store_true",
                    help="for facts whose cited page blocks us, look for them on the church's own site")
    args = ap.parse_args()
    for p in args.files:
        asyncio.run(repair(p.resolve(), args.manual, args.resource_blocked))


if __name__ == "__main__":
    main()
