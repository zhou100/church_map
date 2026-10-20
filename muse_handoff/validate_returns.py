"""Mechanical acceptance checks for Muse returns (plan section 6.5).

Usage:
    python3 muse_handoff/validate_returns.py A_calibration muse_handoff/returns/results_A.csv \
        muse_handoff/returns/new_candidates_A.csv [--received-at 2026-10-19T17:27:00Z]

For a redo file covering only some rows of a batch, pass `-` as the candidates
file and add --redo (IDs must belong to the batch; full coverage not required).
Use batch ALL for a file spanning batches (e.g. the Facebook pass).
Other manifests: --manifest muse_handoff/batch_C_manifest.csv. Candidates-only
check (e.g. task CN): pass `-` as the results file.

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
    "task": {"C", "CN", "D", "E", "F", "L"},
    "candidate_status": {"active", "unresolved"},
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

# ZIPs -> USPS city names for San Mateo County and the South Bay (a ZIP may serve several).
ZIP_CITIES = {
    "94002": {"Belmont"}, "94005": {"Brisbane"}, "94010": {"Burlingame", "Hillsborough"},
    "94014": {"Daly City", "Colma"}, "94015": {"Daly City", "Broadmoor"}, "94019": {"Half Moon Bay"},
    "94025": {"Menlo Park", "Atherton"}, "94027": {"Atherton"}, "94030": {"Millbrae"},
    "94044": {"Pacifica"}, "94061": {"Redwood City"}, "94062": {"Redwood City", "Woodside"},
    "94063": {"Redwood City"}, "94065": {"Redwood City"}, "94066": {"San Bruno"},
    "94070": {"San Carlos"}, "94080": {"South San Francisco"},
    "94401": {"San Mateo"}, "94402": {"San Mateo", "Hillsborough"}, "94403": {"San Mateo"},
    "94404": {"San Mateo", "Foster City"},
    # Coast and south San Mateo County
    "94018": {"El Granada", "Half Moon Bay"}, "94020": {"La Honda"}, "94021": {"Loma Mar"},
    "94028": {"Portola Valley", "Ladera", "Menlo Park"}, "94037": {"Montara"}, "94038": {"Moss Beach"},
    "94060": {"Pescadero"}, "94074": {"San Gregorio"}, "94128": {"San Francisco"},
    # North Santa Clara County (batch C) and South Bay (task CN)
    "94022": {"Los Altos", "Los Altos Hills"}, "94024": {"Los Altos", "Los Altos Hills"},
    "94301": {"Palo Alto"}, "94303": {"Palo Alto", "East Palo Alto"}, "94304": {"Palo Alto"},
    "94305": {"Stanford", "Palo Alto"}, "94306": {"Palo Alto"},
    "94040": {"Mountain View"}, "94041": {"Mountain View"}, "94043": {"Mountain View"},
    "94085": {"Sunnyvale"}, "94086": {"Sunnyvale"}, "94087": {"Sunnyvale"}, "94089": {"Sunnyvale"},
    "95014": {"Cupertino"}, "95008": {"Campbell"}, "95030": {"Los Gatos", "Monte Sereno"}, "95032": {"Los Gatos"},
    "95035": {"Milpitas"}, "95050": {"Santa Clara"}, "95051": {"Santa Clara"}, "95054": {"Santa Clara"},
    "95070": {"Saratoga"},
    **{str(z): {"San Jose"} for z in list(range(95110, 95140)) + [95148]},
    "95002": {"San Jose", "Alviso"},
    # San Francisco and the Fremont area (batch D)
    **{str(z): {"San Francisco"} for z in list(range(94102, 94135)) + [94158]},
    "94536": {"Fremont"}, "94537": {"Fremont"}, "94538": {"Fremont"}, "94539": {"Fremont"},
    "94555": {"Fremont"}, "94560": {"Newark"}, "94587": {"Union City"}, "94586": {"Sunol"},
    # East Bay (batch F). Multi-city sets where one ZIP serves several USPS names.
    **{str(z): {"Oakland"} for z in range(94601, 94622)},
    "94610": {"Oakland", "Piedmont"}, "94611": {"Oakland", "Piedmont"}, "94618": {"Oakland", "Piedmont"},
    "94608": {"Oakland", "Emeryville"}, "94705": {"Berkeley", "Oakland"},
    **{str(z): {"Berkeley"} for z in (94702, 94703, 94704, 94709, 94710, 94720)},
    "94707": {"Berkeley", "Kensington", "Albany"}, "94708": {"Berkeley", "Kensington"},
    "94706": {"Albany", "Kensington", "Berkeley"},
    "94501": {"Alameda"}, "94502": {"Alameda"},
    "94577": {"San Leandro"}, "94578": {"San Leandro", "Ashland", "Cherryland"}, "94579": {"San Leandro"},
    "94580": {"San Lorenzo", "Ashland", "Cherryland", "Hayward"},
    "94541": {"Hayward", "Cherryland", "Ashland"}, "94542": {"Hayward"}, "94544": {"Hayward"}, "94545": {"Hayward"},
    "94546": {"Castro Valley"}, "94552": {"Castro Valley"},
    "94568": {"Dublin"}, "94566": {"Pleasanton"}, "94588": {"Pleasanton"},
    "94550": {"Livermore"}, "94551": {"Livermore"},
    "94582": {"San Ramon"}, "94583": {"San Ramon"}, "94506": {"Danville"}, "94526": {"Danville", "Diablo"},
    "94595": {"Walnut Creek"}, "94596": {"Walnut Creek"}, "94597": {"Walnut Creek"}, "94598": {"Walnut Creek"},
    "94518": {"Concord"}, "94519": {"Concord"}, "94520": {"Concord"}, "94521": {"Concord"},
    "94523": {"Pleasant Hill"}, "94553": {"Martinez"}, "94549": {"Lafayette"}, "94563": {"Orinda"},
    "94556": {"Moraga"}, "94517": {"Clayton"},
    "94801": {"Richmond", "North Richmond"}, "94804": {"Richmond"}, "94805": {"Richmond"},
    "94803": {"Richmond", "El Sobrante", "San Pablo", "Pinole"}, "94806": {"San Pablo", "Richmond", "Rollingwood"},
    "94530": {"El Cerrito", "Richmond", "East Richmond Heights"},
    "94564": {"Pinole"}, "94547": {"Hercules", "Rodeo"}, "94572": {"Rodeo"}, "94525": {"Crockett"},
    "94565": {"Pittsburg", "Bay Point"}, "94509": {"Antioch"}, "94531": {"Antioch"},
    "94513": {"Brentwood"}, "94561": {"Oakley"}, "94548": {"Knightsen"}, "94510": {"Benicia"},
}

FACT_GROUPS = {
    # group -> predicate: is the group "filled" on this row? (kids exists from v3)
    "status": lambda r: r["status"] not in ("", "unresolved"),
    "address": lambda r: bool(r["street_address"]),
    "phone": lambda r: bool(r["phone"]),
    "service": lambda r: bool(r["service_times_verbatim"] or r["service_languages"]),
    "kids": lambda r: bool(r.get("kids_program_verbatim")),
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
# Accepts CJK numerals too ("下午一時半"): a verbatim excerpt must never need rewriting
# to satisfy this check (CN round: Muse edited 4 excerpts to add Arabic time tokens).
TIME_RE = re.compile(r"\d{1,2}(:\d{2})?\s*(a\.?m\.?|p\.?m\.?|am|pm|點|点|時|时|시)|noon|\d{1,2}:\d{2}"
                     r"|[一二三四五六七八九十]{1,3}\s*(時|时|點|点)"
                     r"|\b\d{1,2}(:\d{2})?\s?[ap]\b", re.I)  # Korean 오전 8시; "10A" shorthand
STRICT_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z$")

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
        warn(where, f"zip {z} not in the ZIP table; check manually")
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
    if r.get("checked_at") and not STRICT_TS_RE.match(r["checked_at"]):
        err(where, f"checked_at {r['checked_at']!r} is not YYYY-MM-DDTHH:MM[:SS]Z")
    if ts is None:
        err(where, "checked_at missing or not ISO 8601")
    elif received_at and ts > received_at:
        err(where, f"checked_at {r['checked_at']} is after the file was received ({received_at:%H:%M}Z)")


def check_fact_groups(w: str, r: dict) -> None:
    for g, filled in FACT_GROUPS.items():
        if f"{g}_source_url" not in r or not filled(r):
            continue
        missing = [c for c in (f"{g}_source_url", f"{g}_source_type", f"{g}_excerpt") if not r[c]]
        if missing:
            err(w, f"{g} fact without {', '.join(missing)}")
        if r[f"{g}_source_type"] and r[f"{g}_source_type"] not in ENUMS["source_type"]:
            err(w, f"{g}_source_type={r[f'{g}_source_type']!r} not allowed")
        if r[f"{g}_source_url"] and urlparse(r[f"{g}_source_url"]).path in ("", "/") \
                and r[f"{g}_source_type"] == "denomination":
            warn(w, f"{g}_source_url is a bare homepage; cannot locate the cited listing")
    ex = r.get("address_excerpt", "")
    house = re.match(r"\s*(\d+)", r.get("street_address") or "")
    if house and ex and house.group(1) not in ex:
        err(w, "address_excerpt does not contain the house number")
    if r.get("phone") and r.get("phone_excerpt") and digits(r["phone"])[-4:] not in digits(r["phone_excerpt"]):
        err(w, "phone_excerpt does not contain the phone's last 4 digits")
    if r.get("service_times_verbatim") and r.get("service_excerpt") and not TIME_RE.search(r["service_excerpt"]):
        err(w, "service_excerpt has no time token")
    phone_ctx = NEGATED_PERSONAL_RE.sub("", r.get("notes", "") + " " + r.get("phone_excerpt", ""))
    if r.get("phone") and PERSONAL_PHONE_RE.search(phone_ctx):
        err(w, "phone looks like a personal number (D-2): leave blank, note 'personal number withheld'")
    if r.get("match_confidence") == "high" and r.get("url_evidence") == "name_only":
        err(w, "match_confidence=high but url_evidence=name_only (high needs >=2 independent signals)")


def check_results(batch: str, path: Path, received_at: datetime | None, redo: bool = False,
                  manifest: Path = MANIFEST) -> list[dict]:
    expected = {r["church_id"] for r in csv.DictReader(manifest.open(encoding="utf-8"))
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


def check_candidates_v3(rows: list[dict], received_at: datetime | None) -> None:
    refs = Counter(r["candidate_ref"] for r in rows)
    for ref, n in refs.items():
        if not ref or n > 1:
            err(f"cand:{ref or '(blank)'}", f"candidate_ref blank or repeated ({n}x)")
    for r in rows:
        w = f"{r['candidate_ref']}:{r['candidate_name'][:28]}"
        for col in ("candidate_name", "city", "status", "found_via", "match_confidence", "task"):
            if not r[col]:
                err(w, f"missing required {col}")
        if r["task"] and r["task"] not in ENUMS["task"]:
            err(w, f"task={r['task']!r} not allowed")
        if r["status"] and r["status"] not in ENUMS["candidate_status"]:
            err(w, f"status={r['status']!r} not allowed (candidates: active or unresolved)")
        if r["found_via"] and r["found_via"] not in ENUMS["found_via"]:
            err(w, f"found_via={r['found_via']!r} not allowed")
        if r["match_confidence"] and r["match_confidence"] not in ENUMS["match_confidence"]:
            err(w, f"match_confidence={r['match_confidence']!r} not allowed")
        check_multi(w, "url_evidence", r["url_evidence"], "url_evidence")
        if r["status"] == "active" and not r["status_source_url"]:
            err(w, "status=active without status_source_url")
        if not r["street_address"]:
            warn(w, "no street address (cannot be pinned)")
        check_fact_groups(w, r)
        check_common(w, r, received_at)


def check_candidates(path: Path, received_at: datetime | None) -> list[dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if rows and "candidate_ref" in rows[0]:
        check_candidates_v3(rows, received_at)
        return rows
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
    manifest = MANIFEST
    if "--manifest" in argv:
        i = argv.index("--manifest")
        manifest = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    redo = "--redo" in argv
    argv = [a for a in argv if a != "--redo"]
    if "--received-at" in argv:
        i = argv.index("--received-at")
        received_at = parse_ts(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    batch, results_path, candidates_path = argv[1], Path(argv[2]), Path(argv[3])
    rows = [] if str(results_path) == "-" else check_results(batch, results_path, received_at, redo, manifest)
    for r in rows:
        check_common(r["church_id"], r, received_at)
    cands = [] if str(candidates_path) == "-" else check_candidates(candidates_path, received_at)
    for level, where, msg in sorted(problems, key=lambda p: (p[0], p[1])):
        print(f"{level:5} {where:38} {msg}")
    print(f"\n{sum(p[0] == 'ERROR' for p in problems)} errors, {sum(p[0] == 'WARN' for p in problems)} warnings")
    if rows:
        summarize(rows)
    print(f"\nNew candidates: {len(cands)}; with street address: {sum(1 for r in cands if r['street_address'])}; "
          f"found_via: {dict(Counter(r['found_via'] for r in cands))}")
    return 1 if any(p[0] == "ERROR" for p in problems) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
