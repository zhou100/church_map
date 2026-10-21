"""Church leads from the IRS Exempt Organizations Business Master File (EO BMF).

The BMF is public domain and downloadable per state:

    mkdir -p analytics/exports/irs && curl -fsSL -o analytics/exports/irs/eo_ca.csv \\
        https://www.irs.gov/pub/irs-soi/eo_ca.csv

A lead is a Christian congregation-like record that is in neither the OSM directory
(holyhub.db) nor Muse's returns. It is a lead, not a fact: churches never file Form
990, so a closed church is never removed, and the address is the filing address
(often a home or a mailbox), never evidence of where a congregation meets.

    python3 analytics/scripts/irs_leads.py analytics/exports/irs/eo_ca.csv --state CA \\
        --out muse_handoff/outbox/irs_leads_ca.csv [--muse-area] [--sample 100 --seed 7]

Prints the coverage measurement (how much of the BMF the directory and Muse already
have, and how many of Muse's new congregations the BMF had).
"""
from __future__ import annotations

import argparse
import csv
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "muse_handoff"))
from validate_returns import street_key  # noqa: E402

SEEDS = ROOT / "analytics" / "dbt" / "seeds"

NON_CHRISTIAN_NTEE = ("X30", "X40", "X50", "X70")
NON_CHRISTIAN_RE = re.compile(r"\b(SYNAGOGUE|JEWISH|CHABAD|TORAH|BETH|ISLAMIC|MASJID|MOSQUE|MUSLIM|BUDDHIS\w*|"
                              r"DHARMA|ZEN|SANGHA|HINDU|VEDANTA|SIKH|GURDWARA|JAIN|BAHAI|WICCA\w*|PAGAN|"
                              r"SCIENTOLOGY|SPIRITUALIST|TAOIST|UNITARIAN\w*)\b")
CONGREGATION_RE = re.compile(r"\b(CHURCH|IGLESIA|PARISH|CONGREGATION|CHAPEL|FELLOWSHIP|ASSEMBLY|TABERNACLE|"
                             r"CATHEDRAL|BAPTIST|LUTHERAN|METHODIST|PRESBYTERIAN|EPISCOPAL|PENTECOSTAL|"
                             r"CALVARY|VINEYARD|ADVENTIST|NAZARENE|COVENANT|ORTHODOX|IGREJA|EGLISE|TEMPLO|"
                             r"MINISTERIO|CENTRO CRISTIANO|KOREAN|CHINESE|VIETNAMESE)\b")
NON_CONGREGATION_RE = re.compile(r"\b(FOUNDATION|SCHOOL|ACADEMY|COLLEGE|SEMINARY|UNIVERSITY|CAMP|RADIO|"
                                 r"HOSPITAL|PRESCHOOL|DAYCARE|CHILD CARE|HOUSING|THRIFT|AUXILIARY|"
                                 r"ENDOWMENT|TRUST|ASSOCIATION|CONFERENCE|DIOCESE|PRESBYTERY|SYNOD|"
                                 r"DISTRICT|COUNCIL|NETWORK|ALLIANCE OF)\b")
MAILBOX_RE = re.compile(r"^(P\s*O\s*BOX|POST OFFICE BOX|BOX\s+\d|PMB)")
UNIT_RE = re.compile(r"\b(APT|UNIT|STE|SUITE|PMB|SPC|TRLR)\b|#")
STOP = {"THE", "OF", "IN", "AT", "AND", "INC", "INCORPORATED", "CHURCH", "CA", "CALIFORNIA", "CORP",
        "CORPORATION", "A", "NONPROFIT", "RELIGIOUS", "FOR", "LTD", "CO", "DBA", "IGLESIA", "DE", "LA", "EL",
        "SAN", "SANTA"}
ALIAS = {"SAINT": "ST", "STS": "ST", "MT": "MOUNT", "1ST": "FIRST", "2ND": "SECOND", "CTR": "CENTER"}
LEAD_COLS = ["ein", "irs_name", "irs_street", "irs_city", "irs_zip", "ruling_year", "ntee", "group_exempt"]


def name_tokens(name: str, city: str = "") -> frozenset:
    t = re.sub(r"['’]", "", (name or "").upper())  # "St. Mary's" = "SAINT MARYS"
    t = re.sub(r"[^A-Z0-9 ]", " ", t.replace("&", " AND "))
    city_toks = set(city.upper().split())
    return frozenset(ALIAS.get(x, x) for x in t.split() if x not in STOP and x not in city_toks)


def same_name(a: frozenset, b: frozenset) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    return inter / len(a | b) >= 0.6 or (inter >= 2 and (a <= b or b <= a))


def norm_city(c: str) -> str:
    return re.sub(r"\s+", " ", (c or "").upper().strip())


class Index:
    """Same congregation = same house number + street in the same city or ZIP, or a
    near-identical name in the same city."""

    def __init__(self):
        self.by_city = defaultdict(list)
        self.by_street = defaultdict(set)

    def add(self, rid: str, name: str, city: str, street: str, zipc: str) -> None:
        c = norm_city(city)
        self.by_city[c].append((name_tokens(name, c), rid))
        k = street_key(street or "")
        if k:
            for place in (c, (zipc or "")[:5]):
                if place:
                    self.by_street[(k, place)].add(rid)

    def match(self, name: str, city: str, street: str, zipc: str) -> tuple[str, str] | None:
        c = norm_city(city)
        k = street_key(street or "")
        if k:
            for place in (c, (zipc or "")[:5]):
                if (k, place) in self.by_street:
                    return "street", sorted(self.by_street[(k, place)])[0]
        t = name_tokens(name, c)
        for tt, rid in self.by_city.get(c, ()):
            if same_name(t, tt):
                return "name", rid
        return None


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def bmf_churches(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="latin-1") as f:
        for r in csv.DictReader(f):
            if r["SUBSECTION"] != "03" or not (r["FOUNDATION"] == "10" or r["NTEE_CD"][:2] == "X2"
                                               or r["ACTIVITY"][:3] == "001"):
                continue
            if r["NTEE_CD"][:3] in NON_CHRISTIAN_NTEE or NON_CHRISTIAN_RE.search(r["NAME"]):
                continue
            street = r["STREET"].upper().replace(".", "")
            r["mailbox"] = bool(MAILBOX_RE.match(street) or UNIT_RE.search(street))
            r["congregation_like"] = bool(CONGREGATION_RE.search(r["NAME"])) and not NON_CONGREGATION_RE.search(r["NAME"])
            out.append(r)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bmf", type=Path)
    ap.add_argument("--state", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--db", type=Path, default=ROOT / "holyhub.db")
    ap.add_argument("--muse-area", action="store_true", help="only cities Muse has already worked")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)

    known = Index()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    osm_rows = list(con.execute("select church_id, name, city, address, zip_code from churches where state = ?",
                                (args.state,)))
    con.close()
    for cid, name, city, addr, z in osm_rows:
        known.add(f"osm:{cid}", name, city, addr, z or "")
    results, cands = read_csv(SEEDS / "muse_results.csv"), read_csv(SEEDS / "muse_candidates.csv")
    for r in results:  # Muse's corrected names and streets of directory rows
        known.add(f"osm:{r['church_id']}", r["current_name"], r["city"], r["street_address"], r["zip"])
    for r in cands:
        known.add(f"muse:{r['candidate_id']}", r["candidate_name"], r["city"], r["street_address"], r["zip"])
    muse_cities = ({norm_city(r["city"]) for r in cands + results}
                   | {norm_city(r["known_city"]) for r in read_csv(SEEDS / "muse_manifest.csv")}) - {""}
    # City names repeat across the state (San Jose's Burbank vs the city of Burbank),
    # so the area also needs a 3-digit ZIP prefix Muse has seen.
    muse_zip3 = {r["zip"][:3] for r in cands + results if len(r["zip"]) >= 5}

    churches = bmf_churches(args.bmf)
    leads, how = [], Counter()
    for r in churches:
        m = known.match(r["NAME"], r["CITY"], "" if r["mailbox"] else r["STREET"], r["ZIP"])
        how[m[1].split(":")[0] if m else "neither"] += 1
        if m or not r["congregation_like"] or r["mailbox"]:
            continue
        if args.muse_area and (norm_city(r["CITY"]) not in muse_cities or r["ZIP"][:3] not in muse_zip3):
            continue
        leads.append(dict(ein=r["EIN"], irs_name=r["NAME"], irs_street=r["STREET"], irs_city=r["CITY"].title(),
                          irs_zip=r["ZIP"][:5], ruling_year=r["RULING"][:4], ntee=r["NTEE_CD"],
                          group_exempt="yes" if r["GROUP"] != "0000" else "no"))

    irs = Index()
    for r in churches:
        irs.add(r["EIN"], r["NAME"], r["CITY"], "" if r["mailbox"] else r["STREET"], r["ZIP"])
    new_ids = {r["candidate_id"] for r in cands if not r["possible_match_church_id"] and not r["duplicate_of_church_id"]}
    muse_new = [r for r in cands if r["candidate_id"] in new_ids]
    muse_hit = sum(1 for r in muse_new if irs.match(r["candidate_name"], r["city"], r["street_address"], r["zip"]))
    print(f"{args.state}: {len(churches)} Christian church records; already in the directory {how['osm']}, "
          f"found by Muse {how['muse']}, in neither {how['neither']}")
    print(f"leads (congregation-like name, street address, in neither){' in Muse cities' if args.muse_area else ''}: "
          f"{len(leads)}")
    print(f"Muse discoveries without a directory match that the BMF already lists: {muse_hit} of {len(muse_new)}")

    if args.sample:
        leads = random.Random(args.seed).sample(leads, min(args.sample, len(leads)))
    leads.sort(key=lambda r: (r["irs_city"], r["irs_name"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEAD_COLS)
        w.writeheader()
        w.writerows(leads)
    print(f"wrote {len(leads)} leads -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
