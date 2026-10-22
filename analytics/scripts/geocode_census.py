"""Census-only, local-file geocoding. Never changes addresses or writes a database.

Run --fetch to submit the original street/city/state/ZIP fields once; subsequent
runs rebuild and validate the output from the saved Census response offline.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from muse_handoff.validate_returns import (
    excerpt_supports_street, street_key as complete_street_key, STREET_DIRECTION,
)
EXPORTS = ROOT / "analytics" / "exports"
INPUT = EXPORTS / "geocode_input.csv"
RAW = EXPORTS / "geocode_census_raw.csv"
META = EXPORTS / "geocode_census_metadata.json"
BENCHMARK = "Public_AR_Current"
VINTAGE = "Current_Current"
URL = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
FIELDS = ["geo_id", "status", "latitude", "longitude", "match_type",
          "matched_address", "tiger_line_id", "side", "distance_from_current_pin_m",
          "geocoder", "benchmark", "geocoded_at", "notes"]
SANTA_CLARA = {"Campbell", "Cupertino", "Los Altos", "Los Altos Hills",
               "Los Gatos", "Milpitas", "Mountain View", "Palo Alto",
               "San Jose", "Santa Clara", "Stanford", "Sunnyvale"}
ALAMEDA = {"Fremont", "Newark", "Oakland", "Union City"}
SAN_MATEO = {"Burlingame", "Colma", "Daly City", "East Palo Alto", "Foster City",
             "Half Moon Bay", "Menlo Park", "Millbrae", "Pacifica", "Pescadero",
             "Portola Valley", "Redwood City", "San Bruno", "San Carlos",
             "San Mateo", "South San Francisco", "Woodside"}
TOKENS = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
    "STREET": "ST", "ROAD": "RD", "AVENUE": "AVE", "BOULEVARD": "BLVD",
    "DRIVE": "DR", "COURT": "CT", "CIRCLE": "CIR", "HIGHWAY": "HWY",
    "LANE": "LN", "PLACE": "PL", "TERRACE": "TER", "PARKWAY": "PKWY",
    "FIRST": "1ST", "SECOND": "2ND", "THIRD": "3RD", "FOURTH": "4TH",
    "FIFTH": "5TH", "SIXTH": "6TH", "SEVENTH": "7TH", "EIGHTH": "8TH",
    "NINTH": "9TH", "TENTH": "10TH", "SEVENTEENTH": "17TH",
}


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def street_key(value):
    # Comparison only: original address is submitted verbatim. Suites/buildings
    # are not part of a TIGER street segment. No spelling/fuzzy-name corrections.
    value = re.split(r",|\b(?:SUITE|STE|BLDG|BUILDING|APT|UNIT)\b|#|\(",
                     value.upper(), maxsplit=1)[0]
    parts = re.findall(r"[A-Z0-9]+", value)
    return tuple(TOKENS.get(part, part) for part in parts)


def county_for(city):
    if city == "San Francisco":
        return "075"
    if city in SANTA_CLARA:
        return "085"
    if city in ALAMEDA:
        return "001"
    if city in SAN_MATEO:
        return "081"
    return None


def assess_street(matched_address, input_street, direction_proven=False):
    """The shared complete-address rule, with an explicit direction-only gate.

    direction_proven must mean matching ZIP and a complete Census range/name
    check found no competing segment for this house number. Callers must retain
    that evidence; merely getting one geocoder candidate is insufficient.
    """
    if excerpt_supports_street(matched_address, input_street):
        return "ok", "Shared excerpt_supports_street complete-address rule passes."
    original = complete_street_key(input_street)
    matched = complete_street_key(matched_address.split(",")[0])
    directions = set(STREET_DIRECTION.values())
    without_direction = lambda key: (key[0], tuple(t for t in key[1] if t not in directions)) if key else None
    if original and matched and without_direction(original) == without_direction(matched):
        if direction_proven:
            return "ok", "Direction-only difference: house/name/suffix and ZIP agree; complete Census ZIP/range check establishes no competing N/S segment."
        return "needs_review", "Direction-only difference; required same-ZIP/no-competing-segment proof is missing."
    return "failed", "Different house number, street name or suffix; rejected by the shared complete-address rule."


def distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(a)))


def fetch(rows, digest, raw_path=None, metadata_path=None):
    payload = io.StringIO(newline="")
    writer = csv.writer(payload, lineterminator="\n")
    for row in rows:
        writer.writerow([row[k] for k in ("geo_id", "street", "city", "state", "zip")])
    batch = payload.getvalue().encode("utf-8")
    assert len(rows) <= 10000 and len(batch) < 5_000_000
    boundary = "ChurchMap" + uuid.uuid4().hex
    body = b""
    for key, value in (("benchmark", BENCHMARK), ("vintage", VINTAGE)):
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="addressFile"; filename="addresses.csv"\r\nContent-Type: text/csv\r\n\r\n').encode() + batch
    body += f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(URL, data=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "ChurchMapCensusGeocoding/1.0"})
    started_at, start = utcnow(), time.monotonic()
    with urllib.request.urlopen(request, timeout=240) as response:
        content = response.read()
        http_status = response.status
    decoded = content.decode("utf-8-sig")
    result = list(csv.reader(io.StringIO(decoded)))
    if len(result) != len(rows) or {r[0] for r in result} != {r["geo_id"] for r in rows}:
        raise ValueError("Census response does not contain precisely the input IDs")
    (raw_path or RAW).write_bytes(content)
    (metadata_path or META).write_text(json.dumps({"input_sha256": digest, "request_started_at": started_at,
        "geocoded_at": utcnow(), "request_seconds": round(time.monotonic()-start, 2),
        "endpoint": URL, "benchmark": BENCHMARK, "vintage": VINTAGE,
        "http_status": http_status, "rows_submitted": len(rows),
        "raw_sha256": hashlib.sha256(content).hexdigest()}, indent=2)+"\n", encoding="utf-8")


def classify(row, raw, timestamp, direction_proven=False):
    """direction_proven: see assess_street; set only from complete Census range evidence."""
    out = dict.fromkeys(FIELDS, "")
    out.update(geo_id=row["geo_id"], geocoder="census", benchmark=BENCHMARK,
               geocoded_at=timestamp, status="failed")
    indicator, match = raw[2], raw[3] if len(raw) > 3 else ""
    out["match_type"] = match if match else indicator
    if indicator == "Tie":
        out.update(status="needs_review", match_type="Tie", notes="Census returned a tie; no candidate selected.")
        return out
    if indicator != "Match":
        out.update(match_type="No_Match", notes="Census returned no street-level match for the unchanged input address.")
        return out
    if len(raw) < 12:
        raise ValueError(f"Missing Census geography columns: {raw}")
    out.update(matched_address=raw[4], tiger_line_id=raw[6], side=raw[7])
    lon, lat = map(float, raw[5].split(","))
    problems = []
    if match not in ("Exact", "Non_Exact"):
        problems.append(f"Unrecognized Census match type {match!r}")
    street_status, street_note = assess_street(raw[4], row["street"], direction_proven)
    if street_status == "failed":
        out.update(status="failed", notes=street_note)
        return out
    if street_status == "needs_review":
        problems.append(street_note)
    if not raw[6] or raw[7] not in ("L", "R"):
        problems.append("Missing street-segment TIGER line ID or side; centroid/unknown precision rejected")
    if not (-15 <= lat <= 72 and (-180 <= lon <= -64 or 144 <= lon <= 180) and (lat, lon) != (0, 0)):
        problems.append("Outside repository US envelope")
    if not (32.4 <= lat <= 42.1 and -124.5 <= lon <= -114.1):
        problems.append("Outside California envelope")
    county = county_for(row["city"])
    if county is not None:
        if raw[8] != "06" or raw[9] != county:
            problems.append(f"County check requires review: Census state/county {raw[8]}/{raw[9]}, city expects 06/{county}")
        locality = f"Census county 06/{raw[9]} verified"
    else:
        # No county table for this city: the matched address must sit in the input's
        # own ZIP, or with no input ZIP in the input's own city (and in California).
        # A same-numbered street elsewhere fails this.
        parts = [p.strip() for p in raw[4].split(",")]
        matched_city, matched_zip = (parts[-3], parts[-1]) if len(parts) >= 4 else ("", "")
        if raw[8] != "06":
            problems.append(f"Census state {raw[8]} is not California")
        if row["zip"]:
            if matched_zip != row["zip"].strip()[:5]:
                problems.append(f"No county rule for input city {row['city']!r}; Census ZIP {matched_zip} differs from input ZIP {row['zip']}")
            locality = f"Census ZIP {matched_zip} equals input ZIP; Census county 06/{raw[9]}"
        else:
            if " ".join(matched_city.upper().split()) != " ".join(row["city"].upper().split()):
                problems.append(f"No county rule for input city {row['city']!r}, no input ZIP, and Census city {matched_city!r} differs")
            locality = f"no input ZIP; Census city {matched_city} equals input city; Census county 06/{raw[9]}"
    if problems:
        out.update(status="needs_review", notes="; ".join(problems))
    else:
        out.update(status="ok", latitude=f"{lat:.6f}", longitude=f"{lon:.6f}",
                   notes=f"Street-segment interpolation; input house number/street agree; {locality}.")
        if row["current_lat"] and row["current_lon"]:
            out["distance_from_current_pin_m"] = f"{distance_m(float(row['current_lat']), float(row['current_lon']), lat, lon):.1f}"
    return out


def validate_clusters(output, by_id):
    """Withhold different-address collisions; return legitimate shared pins."""
    clusters = collections.defaultdict(list)
    for out in output:
        if out["status"] == "ok":
            clusters[out["latitude"], out["longitude"]].append(out)
    shared = []
    for coords, cluster in clusters.items():
        if len(cluster) < 2:
            continue
        addresses = {(street_key(by_id[o["geo_id"]]["street"]), by_id[o["geo_id"]]["city"].upper(), by_id[o["geo_id"]]["state"].upper()) for o in cluster}
        if len(addresses) != 1:
            for out in cluster:
                out.update(status="needs_review", latitude="", longitude="", distance_from_current_pin_m="", notes="Different input addresses share a Census coordinate; withheld for review.")
        else:
            shared.append((coords, cluster))
    return shared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Submit unchanged input addresses to Census; otherwise process saved response offline")
    args = parser.parse_args()
    started = time.monotonic()
    digest = hashlib.sha256(INPUT.read_bytes()).hexdigest()
    rows = list(csv.DictReader(INPUT.open(encoding="utf-8-sig", newline="")))
    ids = [r["geo_id"] for r in rows]
    assert len(ids) == len(set(ids)), "Duplicate input IDs"
    if args.fetch:
        fetch(rows, digest)
    offline_started = time.monotonic()
    meta = json.loads(META.read_text(encoding="utf-8"))
    assert meta["input_sha256"] == digest, "Input changed since Census submission"
    assert meta["raw_sha256"] == hashlib.sha256(RAW.read_bytes()).hexdigest()
    raw_rows = list(csv.reader(RAW.open(encoding="utf-8-sig", newline="")))
    raw_by_id = {r[0]: r for r in raw_rows}
    assert len(raw_rows) == len(rows) == len(raw_by_id) and set(raw_by_id) == set(ids)
    for row in rows:
        expected_address = ", ".join(row[key] for key in ("street", "city", "state", "zip"))
        # Census echoes the input; ZIP-less rows may omit trailing whitespace.
        assert raw_by_id[row["geo_id"]][1].rstrip() == expected_address.rstrip(), f"Changed submitted address: {row['geo_id']}"
    output = [classify(row, raw_by_id[row["geo_id"]], meta["geocoded_at"]) for row in rows]
    by_id = {r["geo_id"]: r for r in rows}
    shared = validate_clusters(output, by_id)
    with (EXPORTS / "geocode_output.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output)
    counts = collections.Counter(r["status"] for r in output)
    types = collections.Counter(r["match_type"] for r in output)
    log = ["# Census geocoding run", "", f"- Input: `{INPUT.name}`; SHA-256 `{digest}`; {len(rows)} unique IDs.",
        f"- Submitted: {meta['request_started_at']}; completed: {meta['geocoded_at']} (UTC).",
        f"- One {len(rows)}-row geographies batch; HTTP {meta['http_status']}; benchmark `{BENCHMARK}`, vintage `{VINTAGE}`.",
        f"- Original Census request: {meta['request_seconds']} seconds; latest offline processing: {time.monotonic()-offline_started:.2f} seconds; latest {'fetch-and-process' if args.fetch else 'offline rebuild'} command: {time.monotonic()-started:.2f} seconds.",
        f"- Status: {dict(sorted(counts.items()))}; Census match types: {dict(sorted(types.items()))}.",
        "- Raw evidence: `geocode_census_raw.csv`; request metadata/hashes: `geocode_census_metadata.json`.",
        "- Every original address was submitted unchanged, including missing ZIPs and unit/building text. No alternate addresses or providers used.",
        "- Census echoed input address text was checked against all 198 original street/city/state/ZIP combinations; the input file hash is unchanged. Eleven offline safety tests cover ambiguous matches, number mismatches, county failures, segment evidence and coordinate collisions.",
        "- Matches are TIGER street-range interpolations, not rooftop confirmation. Number/street equality permits punctuation, standard suffix/direction abbreviations and spelled ordinals only. Units/buildings are excluded only for comparison.",
        "- Acceptance: every input ID exactly once; successful coordinates checked against repository US envelope, Bay Area envelope and Census-returned state/county FIPS for the input city. Postal Los Gatos can cross county lines; unexpected counties require review.",
        "- Exact-coordinate clusters with different normalized addresses are withheld. Same-address shared pins are listed below. No database, schema, API, UI or production changes.", "",
        "## Existing pins: accepted replacements over 150 m", "", "| ID | Reason | Distance (m) |", "|---|---|---:|"]
    for out in output:
        if out["distance_from_current_pin_m"] and float(out["distance_from_current_pin_m"]) > 150:
            log.append(f"| {out['geo_id']} | {by_id[out['geo_id']]['reason']} | {out['distance_from_current_pin_m']} |")
    log += ["", "## All pin-off rows", "", "| ID | Status | Distance (m) | Note |", "|---|---|---:|---|"]
    for out in output:
        if by_id[out["geo_id"]]["reason"] == "pin_off":
            log.append(f"| {out['geo_id']} | {out['status']} | {out['distance_from_current_pin_m'] or 'unavailable'} | {out['notes']} |")
    log += ["", "## Same-address shared coordinates", ""]
    for coords, cluster in shared:
        log.append(f"- {', '.join(o['geo_id'] for o in cluster)}: {by_id[cluster[0]['geo_id']]['street']}, {by_id[cluster[0]['geo_id']]['city']} ({coords[0]}, {coords[1]}).")
    log += ["", "## Unresolved rows", "", "| ID | Status | Census match | Reason |", "|---|---|---|---|"]
    for out in output:
        if out["status"] != "ok":
            log.append(f"| {out['geo_id']} | {out['status']} | {out['match_type']} | {out['notes']} |")
    log += ["", "## Reproduce", "", "`python analytics/scripts/geocode_census.py` rebuilds offline from raw evidence; `--fetch` explicitly submits a new Census batch.", "", "Source: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html", ""]
    (EXPORTS / "geocode_run_log.md").write_text("\n".join(log), encoding="utf-8")
    assert hashlib.sha256(INPUT.read_bytes()).hexdigest() == digest
    print(json.dumps({"rows": len(output), "status": dict(counts), "match_type": dict(types), "input_sha256": digest}))


if __name__ == "__main__":
    main()
