"""Mechanical acceptance checks for Muse returns (plan section 6.5).

Usage:
    python3 muse_handoff/validate_returns.py A_calibration muse_handoff/returns/results_A.csv \
        muse_handoff/returns/new_candidates_A.csv [--received-at 2026-10-19T17:27:00Z]

For a redo file covering only some rows of a batch, pass `-` as the candidates
file and add --redo (IDs must belong to the batch; full coverage not required).
Use batch ALL for a file spanning batches (e.g. the Facebook pass).

Prints ERROR lines (rule violations) and WARN lines (needs human review), then a
coverage summary. Exit code 1 if any ERROR. Stdlib only; reads local files only.
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "peninsula_seed_v1.csv"

ENUMS = {
    "entity_type": {"congregation", "religious_house", "non_christian", "business", "other", "unknown"},
    "status": {"active", "closed", "moved", "merged", "unresolved"},
    "source_type": {"own_site", "fb_page", "denomination", "other"},
    "url_evidence": {"address_matches", "phone_matches", "cross_linked", "name_only"},
    "fb_page_evidence": {"links_to_site", "site_links_to_page", "posts_as_church", "address_matches", "phone_matches"},
    "address_is_worship_location": {"yes", "no", "unknown"},
    "pin_check": {"matches", "off", "unknown"},
    "match_confidence": {"high", "medium", "low"},
    "found_via": {"fb_page_search", "fb_group_lead", "web_search", "denomination_directory", "host_church_site"},
}

# San Mateo County ZIPs -> cities (USPS primary names; a ZIP may serve several).
ZIP_CITIES = {
    "94002": {"Belmont"}, "94005": {"Brisbane"}, "94010": {"Burlingame", "Hillsborough"},
    "94014": {"Daly City"}, "94015": {"Daly City"}, "94019": {"Half Moon Bay"},
    "94025": {"Menlo Park", "Atherton"}, "94027": {"Atherton"}, "94030": {"Millbrae"},
    "94044": {"Pacifica"}, "94061": {"Redwood City"}, "94062": {"Redwood City", "Woodside"},
    "94063": {"Redwood City"}, "94065": {"Redwood City"}, "94066": {"San Bruno"},
    "94070": {"San Carlos"}, "94080": {"South San Francisco"},
    "94401": {"San Mateo"}, "94402": {"San Mateo", "Hillsborough"}, "94403": {"San Mateo"},
    "94404": {"San Mateo", "Foster City"},
}

FACT_GROUPS = {
    # group -> predicate: is the group "filled" on this row?
    "status": lambda r: r["status"] not in ("", "unresolved"),
    "address": lambda r: bool(r["street_address"]),
    "phone": lambda r: bool(r["phone"]),
    "service": lambda r: bool(r["service_times_verbatim"] or r["service_languages"]),
}

THIRD_PARTY_HOSTS = ("businessyab.", "yelp.", "google.", "christianity.com", "pwi.org", "mapquest.", "chamberofcommerce.")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Phrases produced by search/places tools rather than by the cited page.
TOOL_OUTPUT_RE = re.compile(r"away from query location|do not trust other web sources|operating status:|account type:|stats: \d", re.I)
LANG_ALIASES = {
    "spanish": ("spanish", "español", "espanol", "espanõl"),
    "mandarin": ("mandarin", "普通話", "普通话", "國語", "国语"),
    "cantonese": ("cantonese", "粵語", "粤语", "廣東話", "广东话"),
    "vietnamese": ("vietnamese", "tiếng việt", "tieng viet"),
    "japanese": ("japanese", "日本語", "日語", "日语"),
}
NEGATED_PERSONAL_RE = re.compile(r"\bnot (identified as |labell?ed as |a )?personal\b", re.I)
PERSONAL_PHONE_RE = re.compile(r"\b(cell|mobile|personal|rector's|pastor's|priest's|father's)\b", re.I)
TIME_RE = re.compile(r"\d{1,2}(:\d{2})?\s*(a\.?m\.?|p\.?m\.?|am|pm|點|点|時|时)|noon|\d{1,2}:\d{2}", re.I)

problems: list[tuple[str, str, str]] = []


def err(where: str, msg: str) -> None:
    problems.append(("ERROR", where, msg))


def warn(where: str, msg: str) -> None:
    problems.append(("WARN", where, msg))


def is_url(u: str) -> bool:
    p = urlparse(u)
    return p.scheme in ("http", "https") and bool(p.netloc)


def is_fb(u: str) -> bool:
    return "facebook.com" in urlparse(u).netloc


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def parse_ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_multi(where: str, col: str, value: str, enum: str) -> None:
    for part in filter(None, value.split(";")):
        if part not in ENUMS[enum]:
            err(where, f"{col}={part!r} not allowed")


def check_zip_city(where: str, r: dict) -> None:
    z, city = r.get("zip", ""), r.get("city", "")
    if not z:
        if r.get("street_address"):
            warn(where, "street_address without zip")
        return
    if not re.fullmatch(r"\d{5}", z):
        err(where, f"zip {z!r} is not 5 digits")
    elif z not in ZIP_CITIES:
        warn(where, f"zip {z} not in San Mateo County table; check manually")
    elif city and city not in ZIP_CITIES[z]:
        err(where, f"zip {z} belongs to {sorted(ZIP_CITIES[z])}, not {city!r}")


def check_common(where: str, r: dict, received_at: datetime | None) -> None:
    for col, val in r.items():
        if val and (col.endswith("_url") or col == "official_url") and not is_url(val):
            err(where, f"{col} is not an http(s) URL")
        if val and col.endswith("excerpt") and len(val) > 200:
            err(where, f"{col} is {len(val)} chars (>200)")
        if val and EMAIL_RE.search(val):
            err(where, f"{col} contains an email address")
        if val and col.endswith("excerpt") and TOOL_OUTPUT_RE.search(val):
            err(where, f"{col} reads like search/places-tool output, not text from the cited page")
        if val and col.endswith("source_url") and any(h in val for h in THIRD_PARTY_HOSTS):
            warn(where, f"{col} is a third-party listing ({urlparse(val).netloc})")
    if r.get("official_url") and is_fb(r["official_url"]):
        err(where, "official_url is a facebook.com URL")
    if r.get("facebook_page_url"):
        if not is_fb(r["facebook_page_url"]):
            err(where, "facebook_page_url is not facebook.com")
        if not r.get("fb_page_evidence"):
            err(where, "facebook_page_url without fb_page_evidence (S2 requires at least one)")
        check_multi(where, "fb_page_evidence", r.get("fb_page_evidence", ""), "fb_page_evidence")
    if r.get("fb_last_post_date"):
        try:
            if date.fromisoformat(r["fb_last_post_date"]) > date.today():
                err(where, "fb_last_post_date is in the future")
        except ValueError:
            err(where, "fb_last_post_date is not YYYY-MM-DD")
    if r.get("street_address") and not re.match(r"\s*\d", r["street_address"]):
        err(where, "street_address has no leading house number")
    if r.get("state") and r["state"] != "CA":
        err(where, f"state={r['state']!r}")
    check_zip_city(where, r)
    ts = parse_ts(r.get("checked_at", ""))
    if ts is None:
        err(where, "checked_at missing or not ISO 8601")
    elif received_at and ts > received_at:
        err(where, f"checked_at {r['checked_at']} is after the file was received ({received_at:%H:%M}Z)")


def check_results(batch: str, path: Path, received_at: datetime | None, redo: bool = False) -> list[dict]:
    expected = {r["church_id"] for r in csv.DictReader(MANIFEST.open(encoding="utf-8"))
                if batch == "ALL" or r["batch"] == batch}
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    ids = Counter(r["church_id"] for r in rows)
    for cid, n in ids.items():
        if n > 1:
            err(cid, f"appears {n} times")
    for cid in (set() if redo else expected - set(ids)):
        err(cid, "missing from results")
    for cid in set(ids) - expected:
        err(cid, "not in this batch of the manifest")

    for r in rows:
        w = r["church_id"]
        for col in ("entity_type", "status", "pin_check", "match_confidence"):
            if r[col] not in ENUMS[col]:
                err(w, f"{col}={r[col]!r} not allowed")
        if r["address_is_worship_location"] and r["address_is_worship_location"] not in ENUMS["address_is_worship_location"]:
            err(w, "address_is_worship_location not allowed")
        check_multi(w, "url_evidence", r["url_evidence"], "url_evidence")
        if r["official_url"] and not r["url_evidence"]:
            err(w, "official_url without url_evidence")
        if r["minutes_spent"] and not r["minutes_spent"].isdigit():
            err(w, "minutes_spent is not an integer")

        for g, filled in FACT_GROUPS.items():
            if not filled(r):
                continue
            missing = [c for c in (f"{g}_source_url", f"{g}_source_type", f"{g}_excerpt") if not r[c]]
            if missing:
                err(w, f"{g} fact without {', '.join(missing)}")
            if r[f"{g}_source_type"] and r[f"{g}_source_type"] not in ENUMS["source_type"]:
                err(w, f"{g}_source_type={r[f'{g}_source_type']!r} not allowed")
            if r[f"{g}_source_url"] and urlparse(r[f"{g}_source_url"]).path in ("", "/") \
                    and r[f"{g}_source_type"] == "denomination":
                warn(w, f"{g}_source_url is a bare homepage; cannot locate the cited listing")

        ex = r["address_excerpt"]
        house = re.match(r"\s*(\d+)", r["street_address"] or "")
        if house and ex and house.group(1) not in ex:
            err(w, "address_excerpt does not contain the house number")
        if r["zip"] and ex and r["zip"] not in ex:
            warn(w, f"address_excerpt does not contain zip {r['zip']}")
        if r["phone"] and r["phone_excerpt"] and digits(r["phone"])[-4:] not in digits(r["phone_excerpt"]):
            err(w, "phone_excerpt does not contain the phone's last 4 digits")
        if r["service_times_verbatim"] and r["service_excerpt"] and not TIME_RE.search(r["service_excerpt"]):
            err(w, "service_excerpt has no time token")
        seen = (r["service_excerpt"] + " " + r["service_times_verbatim"]).lower()
        for lang in filter(None, r["service_languages"].split(";")):
            aliases = LANG_ALIASES.get(lang.lower(), (lang.lower(),))
            if lang != "English" and not any(a in seen for a in aliases):
                warn(w, f"service language {lang} not visible in excerpt or verbatim times")

        # D-2: personal numbers are never kept, even if the church published them.
        phone_ctx = NEGATED_PERSONAL_RE.sub("", r["notes"] + " " + r["phone_excerpt"])
        if r["phone"] and PERSONAL_PHONE_RE.search(phone_ctx):
            err(w, "phone looks like a personal number (D-2): leave blank, note 'personal number withheld'")

        # Consistency between verdicts.
        if r["match_confidence"] == "high" and r["url_evidence"] == "name_only":
            err(w, "match_confidence=high but url_evidence=name_only (high needs >=2 independent signals)")
        if r["match_confidence"] == "high" and r["status"] == "unresolved":
            warn(w, "match_confidence=high on an unresolved row")
        if r["status"] == "closed" and "temporarily" in r["status_excerpt"].lower():
            warn(w, "status=closed but the excerpt says temporarily closed")
        if r["entity_type"] != "congregation" and r["status"] == "closed":
            warn(w, "entity_type should describe the named (closed) entity, not the building's current occupant")
        if r["status_source_type"] == "own_site" and r["status_source_url"] and \
                r["official_url"] and urlparse(r["official_url"]).netloc.split("www.")[-1] not in r["status_source_url"]:
            warn(w, "status source typed own_site but not on the official domain")
    return rows


def check_candidates(path: Path, received_at: datetime | None) -> list[dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for i, r in enumerate(rows, 1):
        w = f"cand{i}:{r['candidate_name'][:30]}"
        for col in ("candidate_name", "city", "source_url", "excerpt"):
            if not r[col]:
                err(w, f"missing required {col}")
        if r["source_type"] not in ENUMS["source_type"]:
            err(w, f"source_type={r['source_type']!r} not allowed")
        if r["found_via"] not in ENUMS["found_via"]:
            err(w, f"found_via={r['found_via']!r} not allowed")
        house = re.match(r"\s*(\d+)", r["street_address"] or "")
        if house and house.group(1) not in r["excerpt"]:
            warn(w, "street_address not supported by the excerpt")
        if not r["street_address"]:
            warn(w, "no street address (cannot be pinned)")
        if r["source_type"] == "other":
            warn(w, "only a non-official source")
        check_common(w, r, received_at)
    stamps = Counter(r["checked_at"] for r in rows)
    if len(rows) > 3 and len(stamps) == 1:
        warn("candidates", f"all {len(rows)} rows share checked_at {next(iter(stamps))}; likely reconstructed")
    return rows


def summarize(rows: list[dict]) -> None:
    n = len(rows)
    c = lambda pred: sum(1 for r in rows if pred(r))
    print(f"\nResults: {n} rows")
    print("  status:", dict(Counter(r["status"] for r in rows)))
    print("  entity_type:", dict(Counter(r["entity_type"] for r in rows)))
    print(f"  official_url: {c(lambda r: r['official_url'])} "
          f"(name_only: {c(lambda r: r['url_evidence'] == 'name_only')})")
    print(f"  facebook_page_url: {c(lambda r: r['facebook_page_url'])}; fb_last_post_date: {c(lambda r: r['fb_last_post_date'])}")
    print(f"  street_address: {c(lambda r: r['street_address'])} "
          f"(own_site source: {c(lambda r: r['street_address'] and r['address_source_type'] == 'own_site')})")
    print(f"  phone: {c(lambda r: r['phone'])}; service times: {c(lambda r: r['service_times_verbatim'])}; "
          f"languages stated: {c(lambda r: r['service_languages'])}")
    visit_ready = c(lambda r: r["status"] == "active" and r["street_address"]
                    and r["address_source_type"] in ("own_site", "denomination")
                    and r["url_evidence"] not in ("", "name_only")
                    and r["match_confidence"] == "high")
    print(f"  candidate visit-ready (active + own/denomination address + verified URL + high), pending audit: {visit_ready}")
    print("  checked_at values:", dict(Counter(r["checked_at"] for r in rows)))
    print(f"  minutes_spent total: {sum(int(r['minutes_spent'] or 0) for r in rows)}")


def main(argv: list[str]) -> int:
    received_at = None
    redo = "--redo" in argv
    argv = [a for a in argv if a != "--redo"]
    if "--received-at" in argv:
        i = argv.index("--received-at")
        received_at = parse_ts(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    batch, results_path, candidates_path = argv[1], Path(argv[2]), Path(argv[3])
    rows = check_results(batch, results_path, received_at, redo)
    for r in rows:
        check_common(r["church_id"], r, received_at)
    cands = [] if str(candidates_path) == "-" else check_candidates(candidates_path, received_at)
    for level, where, msg in sorted(problems, key=lambda p: (p[0], p[1])):
        print(f"{level:5} {where:38} {msg}")
    print(f"\n{sum(p[0] == 'ERROR' for p in problems)} errors, {sum(p[0] == 'WARN' for p in problems)} warnings")
    summarize(rows)
    print(f"\nNew candidates: {len(cands)}; with street address: {sum(1 for r in cands if r['street_address'])}; "
          f"found_via: {dict(Counter(r['found_via'] for r in cands))}")
    return 1 if any(p[0] == "ERROR" for p in problems) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
