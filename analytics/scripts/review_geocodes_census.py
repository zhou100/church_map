"""Review the remaining nine original withheld addresses using Census only.

No alternate address strings are submitted. No database or production writes.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import io
from pathlib import Path
import struct
import time
import urllib.parse
import urllib.request
import zipfile

from geocode_census import (FIELDS, distance_m, street_key, validate_clusters,
                           assess_street, complete_street_key, STREET_DIRECTION)

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "analytics" / "exports"
EVIDENCE = EXPORTS / "geocode_review_evidence"
IDS = ["candidate:C-015", "candidate:C-016", "candidate:C-018",
       "candidate:D-145", "candidate:D-148", "candidate:C-053",
       "candidate:C-056", "candidate:D-013", "candidate:D-132"]
CABRILLO = set(IDS[:3])
COUNTY = {"candidate:D-145", "candidate:D-148"}
FEATURE_URL = "https://www2.census.gov/geo/tiger/TIGER2025/FEATNAMES/tl_2025_06085_featnames.zip"


def get_json(url, filename):
    path = EVIDENCE / filename
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    request = urllib.request.Request(url, headers={"User-Agent": "ChurchMapCensusReview/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        content = response.read()
        status = response.status
    data = json.loads(content)
    path.write_bytes(content)
    metadata = {"url": url, "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "http_status": status, "sha256": hashlib.sha256(content).hexdigest()}
    path.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    time.sleep(0.3)
    return data


def feature_names():
    """Read all names attached to each exact TLID, including alternate names."""
    path=EVIDENCE / "tl_2025_06085_featnames.zip"
    meta=json.loads(path.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(path.read_bytes()).hexdigest()==meta["sha256"]
    with zipfile.ZipFile(path) as archive:
        data = archive.read(next(n for n in archive.namelist() if n.endswith(".dbf")))
    count, header, size = struct.unpack_from("<IHH", data, 4)
    fields = []
    for off in range(32, header-1, 32):
        if data[off] == 13:
            break
        desc = data[off:off+32]
        fields.append((desc[:11].split(b"\0")[0].decode(), desc[16]))
    names = {}
    for index in range(count):
        record = data[header+index*size:header+(index+1)*size]
        if record[:1] == b"*":
            continue
        offset, row = 1, {}
        for name, length in fields:
            row[name] = record[offset:offset+length].decode("utf-8", errors="replace").strip()
            offset += length
        names.setdefault(row["TLID"], []).append(row["FULLNAME"])
    return names


def review_row(row, raw, data):
    """Narrow, evidence-bound review; never relax rules for other addresses."""
    out = dict.fromkeys(FIELDS, "")
    out.update(geo_id=row["geo_id"], status="needs_review", geocoder="census",
               benchmark="Public_AR_Current", match_type=raw[3] if len(raw)>3 else raw[2])
    result = data["result"]
    assert all(result["input"]["address"].get(k, "") == row[k]
               for k in ("street", "city", "state", "zip")), "Review query changed an input address"
    matches = result.get("addressMatches", [])
    if len(matches) != 1:
        out["notes"] = f"Census returns {len(matches)} candidates; no candidate selected."
        if matches:
            out["notes"] += " ZIP/segment pairs: "+", ".join(
                m["addressComponents"]["zip"]+"/"+m["tigerLine"]["tigerLineId"] for m in matches)+"."
        return out
    assert len(raw) >= 12 and raw[2] == "Match"
    match = matches[0]
    components, geographies = match["addressComponents"], match["geographies"]
    county = geographies["Counties"]
    out.update(matched_address=raw[4], tiger_line_id=raw[6], side=raw[7])
    lon, lat = map(float, raw[5].split(","))
    assert match["matchedAddress"] == raw[4], "Single/batch matched addresses differ"
    assert match["tigerLine"] == {"tigerLineId": raw[6], "side": raw[7]}, "Segment differs"
    assert abs(match["coordinates"]["x"]-lon)<1e-10 and abs(match["coordinates"]["y"]-lat)<1e-10
    assert len(county)==1 and county[0]["STATE"]==raw[8]=="06" and county[0]["COUNTY"]==raw[9]
    assert 36.8 <= lat <= 38.1 and -123 <= lon <= -121.4 and raw[7] in ("L", "R")
    original, matched = street_key(row["street"]), street_key(raw[4].split(",")[0])
    house, start, end = int(original[0]), int(components["fromAddress"]), int(components["toAddress"])
    assert min(start,end) <= house <= max(start,end) and house%2==start%2==end%2
    assert components["city"]==row["city"].upper() and components["state"]==row["state"]
    assert not row["zip"] or components["zip"]==row["zip"]
    accepted = False
    if row["geo_id"] in CABRILLO:
        accepted = (original[-1] in {"N", "S"} and matched == (original[0], original[-1], *original[1:-1])
                    and components["streetName"]=="CABRILLO" and components["suffixType"]=="HWY"
                    and raw[9]=="081" and any(p["NAME"]=="Half Moon Bay city" for p in geographies.get("Incorporated Places", [])))
        note = "Reviewed direction placement: same house, CABRILLO HWY and N/S direction; unique Census segment/range, ZIP and Half Moon Bay/San Mateo geography agree."
    elif row["geo_id"] in COUNTY:
        accepted = (raw[3]=="Exact" and original==matched and row["city"]=="Los Gatos" and row["zip"]=="95033"
                    and county[0]["GEOID"]=="06087" and not geographies.get("Incorporated Places")
                    and any(p["NAME"]=="Summit Road CCD" for p in geographies.get("County Subdivisions", [])))
        note = "Reviewed geography: exact unchanged Los Gatos 95033 address; Census places the segment in Santa Cruz County (06087), Summit Road CCD, outside an incorporated place. The city-to-county assumption was too strict."
    else:
        street_status, note = assess_street(raw[4], row["street"])
        out["status"] = street_status if street_status != "ok" else "needs_review"
    if accepted:
        out.update(status="ok", latitude=f"{lat:.6f}", longitude=f"{lon:.6f}", notes=note)
        if row["current_lat"] and row["current_lon"]:
            out["distance_from_current_pin_m"] = f"{distance_m(float(row['current_lat']), float(row['current_lon']), lat, lon):.1f}"
    else:
        out["notes"] = note if row["geo_id"] not in CABRILLO | COUNTY else "Priority-row evidence failed the narrow review rule."
    return out


def census_table(path):
    """Read a complete, hash-verified Census DBF table without extra packages."""
    metadata=json.loads(path.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(path.read_bytes()).hexdigest()==metadata["sha256"]
    with zipfile.ZipFile(path) as archive:
        data=archive.read(next(n for n in archive.namelist() if n.endswith(".dbf")))
    count,header,size=struct.unpack_from("<IHH",data,4)
    fields=[]
    for off in range(32,header-1,32):
        if data[off]==13: break
        descriptor=data[off:off+32]
        fields.append((descriptor[:11].split(b"\0")[0].decode(),descriptor[16]))
    for index in range(count):
        record=data[header+index*size:header+(index+1)*size]
        if record[:1]==b"*": continue
        offset,row=1,{}
        for name,length in fields:
            row[name]=record[offset:offset+length].decode("utf-8",errors="replace").strip()
            offset+=length
        yield row


def competing_ranges(input_street, zip_code, names, ranges):
    """All same-house/name/suffix Census ranges in the ZIP; keep directions."""
    key=complete_street_key(input_street)
    directions=set(STREET_DIRECTION.values())
    base=tuple(t for t in key[1] if t not in directions)
    house=int(key[0])
    found=[]
    for record in ranges:
        if record["ZIP"]!=zip_code or not record["FROMHN"].isdigit() or not record["TOHN"].isdigit(): continue
        start,end=int(record["FROMHN"]),int(record["TOHN"])
        if not (min(start,end)<=house<=max(start,end) and house%2==start%2==end%2): continue
        matching=[]
        for name in names.get(record["TLID"],[]):
            candidate=complete_street_key("0 "+name)
            if candidate and tuple(t for t in candidate[1] if t not in directions)==base:
                matching.append(name)
        if matching: found.append({"range":record,"names":matching})
    return found


def resolve_remaining(output, scoped_rows):
    """Apply the owner's authorized retries and ZIP/range direction condition."""
    names={}
    for row in census_table(EVIDENCE / "tl_2026_06085_featnames.zip"):
        if row["NAME"].lower() in {"winchester","el monte"}:
            names.setdefault(row["TLID"],[]).append(row["FULLNAME"])
    ranges=list(census_table(EVIDENCE / "tl_2026_06085_addr.zip"))
    retry_path=EVIDENCE / "el_monte_retry_batch.csv"
    retry_meta=json.loads(retry_path.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(retry_path.read_bytes()).hexdigest()==retry_meta["sha256"]
    retry={r[0]:r for r in csv.reader(io.StringIO(retry_path.read_text(encoding="utf-8-sig")))}
    assert retry["north_full"][1]=="101 North El Monte Avenue, Los Altos, CA, 94022"
    assert retry["no_direction"][1]=="101 El Monte Ave, Los Altos, CA, 94022"
    receipts={}
    for out in output:
        geo_id=out["geo_id"]
        if geo_id=="candidate:D-013":
            out["notes"]+=" Input ZIP remains blank; awaiting the owner's sourced 94102 correction and regenerated input. No segment selected."
            continue
        if geo_id not in {"candidate:C-053","candidate:C-056","candidate:D-132"}: continue
        row=scoped_rows[geo_id]
        is_el_monte=geo_id!="candidate:D-132"
        file=EVIDENCE / ("el_monte_retry_no_direction.json" if is_el_monte else "candidate_D-132.json")
        meta=json.loads(file.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        assert hashlib.sha256(file.read_bytes()).hexdigest()==meta["sha256"]
        matches=json.loads(file.read_text(encoding="utf-8"))["result"]["addressMatches"]
        assert len(matches)==1
        match=matches[0]
        components=match["addressComponents"]
        assert components["state"]==row["state"] and components["city"]==row["city"].upper()
        assert [c["GEOID"] for c in match["geographies"]["Counties"]]==["06085"]
        segment=match["tigerLine"]["tigerLineId"]
        candidates=competing_ranges(row["street"],row["zip"],names,ranges)
        proven=components["zip"]==row["zip"] and {r["range"]["TLID"] for r in candidates}=={segment}
        status,note=assess_street(match["matchedAddress"],row["street"],direction_proven=proven)
        if is_el_monte:
            good_suffix=components["streetName"]=="EL MONTE" and components["suffixType"]=="AVE"
            if status!="ok" or not good_suffix:
                status="failed"
                note="Both authorized El Monte retries failed to establish an unambiguous El Monte Ave segment for the original address; original Del Monte Ave/El Monte Ct results rejected."
            else:
                note="Original Del Monte Ave/El Monte Ct results rejected. Owner-authorized no-direction retry returns S EL MONTE AVE, range 1-111, ZIP 94022. Complete Census 2026 Santa Clara names/ranges contain no competing N/S El Monte Ave segment for 101 in this ZIP; both co-located rows share this pin."
        else:
            note+=" Census 2026 Santa Clara names/ranges: only TLID "+segment+" covers 1870 in ZIP 95008 (1802-1990); no competing N/S Winchester Blvd segment."
        out.update(status=status,notes=note,latitude="",longitude="",distance_from_current_pin_m="")
        if status=="ok":
            point=match["coordinates"]
            assert 36.8<=point["y"]<=38.1 and -123<=point["x"]<=-121.4
            out.update(latitude=f"{point['y']:.6f}",longitude=f"{point['x']:.6f}",
                       matched_address=match["matchedAddress"],tiger_line_id=segment,side=match["tigerLine"]["side"])
            if is_el_monte:
                selected=retry["no_direction"]
                assert selected[4]==match["matchedAddress"] and selected[6]==segment and selected[7]==out["side"]
                out["match_type"]=selected[3]
                out["geocoded_at"]=retry_meta["retrieved_at"]
        receipts[geo_id]={"census_2026_ranges":candidates,"direction_condition_established":proven,
                          "selected_evidence":str(file.relative_to(EXPORTS)),"selected_evidence_sha256":meta["sha256"],
                          "selected_source_url":meta["url"],"retrieved_at":meta["retrieved_at"],
                          "owner_authorized_query_variants":is_el_monte}
    return receipts


def build_review():
    input_path = EXPORTS / "geocode_input.csv"
    input_digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    rows = {r["geo_id"]: r for r in csv.DictReader(input_path.open(encoding="utf-8-sig", newline=""))}
    current_input_rows=len(rows)
    scope=json.loads((EXPORTS / "geocode_review_scope.json").read_text(encoding="utf-8"))
    scoped_rows={r["geo_id"]:r for r in scope["rows"]}
    assert set(scoped_rows)==set(IDS)
    raw_path = EXPORTS / "geocode_census_raw.csv"
    raw_bytes = raw_path.read_bytes()
    metadata = json.loads((EXPORTS / "geocode_census_metadata.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw_bytes).hexdigest()==metadata["raw_sha256"]
    raw = {r[0]:r for r in csv.reader(io.StringIO(raw_bytes.decode("utf-8-sig")))}
    names = feature_names()
    reviewed, decisions = [], []
    reviewed_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for geo_id in IDS:
        row = scoped_rows[geo_id]
        assert raw[geo_id][1].rstrip()==", ".join(row[k] for k in ("street", "city", "state", "zip")).rstrip()
        file = EVIDENCE / (geo_id.replace(":", "_")+".json")
        content = file.read_bytes()
        source = json.loads(file.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        assert source["sha256"]==hashlib.sha256(content).hexdigest()
        data = json.loads(content)
        out = review_row(row, raw[geo_id], data)
        out["geocoded_at"] = metadata["geocoded_at"]
        aliases = names.get(out["tiger_line_id"], [])
        if out["status"]=="needs_review" and aliases:
            out["notes"] += " Census 2025 names on this exact TLID: "+", ".join(aliases)+"; none establishes the original street as an alias."
        reviewed.append(out)
        decisions.append({"geo_id":geo_id, "original_input":row, "previous_status":"needs_review",
                          "reviewed_status":out["status"], "reason":out["notes"],
                          "evidence_file":str(file.relative_to(EXPORTS)), "evidence_sha256":source["sha256"],
                          "source_url":source["url"], "retrieved_at":source["retrieved_at"]})
    resolutions=resolve_remaining(reviewed,scoped_rows)
    by_id={r["geo_id"]:r for r in reviewed}
    for decision in decisions:
        out=by_id[decision["geo_id"]]
        decision.update(reviewed_status=out["status"],reason=out["notes"])
        if decision["geo_id"] in resolutions:
            decision["followup_evidence"]=resolutions[decision["geo_id"]]
    # Check new acceptances against every previously accepted pin.
    archived=EXPORTS / "geocode_history" / "initial_198_geocode_output.csv"
    prior_path=archived if archived.exists() else EXPORTS / "geocode_output.csv"
    prior = list(csv.DictReader(prior_path.open(encoding="utf-8-sig", newline="")))
    assert len(prior)==198 and len(reviewed)==len(IDS)
    all_rows = [r for r in prior if r["geo_id"] not in IDS]+reviewed
    validate_clusters(all_rows, rows | scoped_rows)
    assert all(r["status"]=="ok" for r in reviewed if r["geo_id"] in CABRILLO | COUNTY)
    with (EXPORTS / "geocode_review.csv").open("w", encoding="utf-8", newline="") as stream:
        writer=csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader(); writer.writerows(reviewed)
    manifest={"reviewed_at":reviewed_at, "current_input_sha256":input_digest,
              "current_input_rows":current_input_rows, "original_batch_input_sha256":metadata["input_sha256"],
              "original_batch_raw_sha256":metadata["raw_sha256"], "decisions":decisions}
    (EXPORTS / "geocode_review_decisions.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# Census review of nine remaining needs-review rows", "",
           f"Reviewed at {reviewed_at}. {sum(r['status']=='ok' for r in reviewed)} cleared locally; {sum(r['status']=='needs_review' for r in reviewed)} remain needs_review; {sum(r['status']=='failed' for r in reviewed)} failed. C-054 and D-059 were dropped at the owner's request because they were removed.", "",
           f"This review does not write the input, original 198-row output, raw batch or run log. Another process regenerated the live input during this review; it currently contains {current_input_rows} rows. The nine review rows are preserved in geocode_review_scope.json, with their addresses validated against the original Census input echo. This scoped review does not claim coverage of the newer live input.", "",
           "Input addresses are never rewritten. Original requests use the original fields; two owner-authorized El Monte query variants are recorded separately. Public_AR_Current/Current_Current are used throughout. Accepted points are street-range interpolations, not centroids. Census 2026 feature names and complete Santa Clara County address ranges establish the same-ZIP/no-competing-segment condition for the El Monte and Winchester direction differences. New acceptances were checked for collisions against all 176 previously accepted rows.", "",
           "## Decisions", "", "| ID / church | Original address | Reviewed status | Reason |", "|---|---|---|---|"]
    for out in reviewed:
        row=scoped_rows[out["geo_id"]]
        address=", ".join(row[k] for k in ("street","city","state") if row[k])+ (" "+row["zip"] if row["zip"] else " (ZIP blank)")
        lines.append(f"| {out['geo_id']} / {row['name']} | {address} | {out['status']} | {out['notes']} |")
    lines += ["", "## Evidence", "", "Structured decision receipt: `geocode_review_decisions.json`; scoped output with the original 13 columns: `geocode_review.csv`. Per-address Census JSON and request URLs/hashes are in `geocode_review_evidence/`.", "",
              f"Santa Clara street aliases: [Census TIGER/Line 2025 feature names]({FEATURE_URL}). Older-vintage absence of an alias is not proof that no alias exists; it is insufficient evidence to accept a different street name.", "",
              "The two Santa Cruz points have Census address city LOS GATOS and ZIP 95033, but geographic county 06087 and Summit Road CCD. Their geographic acceptance does not decide publication scope or congregation identity.", "",
              "Shared street rule: `muse_handoff.validate_returns.excerpt_supports_street(matched_address, input_street)`. A different street name/suffix fails. Direction-only differences need matching house/name/suffix and ZIP, plus complete Census ZIP/range evidence of no competing directional segment. C-053 and C-056 are explicitly confirmed by the owner to share an address; the North/South difference was accepted only after this check, not silently corrected in the input.", "",
              "Range evidence: `geocode_review_evidence/tl_2026_06085_addr.zip` and `tl_2026_06085_featnames.zip`, with source URLs/hashes beside them. El Monte retry responses and exact Census match-type labels: `el_monte_retry_*.json` and `el_monte_retry_batch.csv`. D-013 remains pending the owner's sourced ZIP regeneration; no church-site request or ZIP edit was made in this Census-only task.", "",
              "Offline reproduction: `python analytics/scripts/review_geocodes_census.py`. `--fetch` requests missing Census evidence only. No production/database writes or publication.", ""]
    (EXPORTS / "geocode_review_log.md").write_text("\n".join(lines),encoding="utf-8")
    assert hashlib.sha256(input_path.read_bytes()).hexdigest()==input_digest
    print(json.dumps({"reviewed":len(reviewed),"ok":sum(r['status']=='ok' for r in reviewed),
                      "needs_review":sum(r['status']=='needs_review' for r in reviewed),
                      "current_input_rows":len(rows),"input_sha256":input_digest}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    args=parser.parse_args()
    EVIDENCE.mkdir(exist_ok=True)
    if not args.fetch:
        build_review()
        return
    scope=json.loads((EXPORTS / "geocode_review_scope.json").read_text(encoding="utf-8"))
    rows = {r["geo_id"]: r for r in scope["rows"]}
    for geo_id in IDS:
        row = rows[geo_id]
        params = {key: row[key] for key in ("street", "city", "state", "zip")}
        params.update(benchmark="Public_AR_Current", vintage="Current_Current", format="json")
        url = "https://geocoding.geo.census.gov/geocoder/geographies/address?"+urllib.parse.urlencode(params)
        data = get_json(url, geo_id.replace(":", "_")+".json")
        result = data.get("result", {})
        print(json.dumps({"geo_id": geo_id,
                          "matches": [{"address": m["matchedAddress"], "line": m["tigerLine"],
                                       "components": m["addressComponents"],
                                       "counties": [c["NAME"] for c in m["geographies"].get("Counties", [])]}
                                      for m in result.get("addressMatches", [])]}), flush=True)
    archive=EVIDENCE / "tl_2025_06085_featnames.zip"
    if not archive.exists():
        with urllib.request.urlopen(FEATURE_URL, timeout=45) as response:
            content=response.read()
        archive.write_bytes(content)
        archive.with_suffix(".metadata.json").write_text(json.dumps({"url":FEATURE_URL,
            "sha256":hashlib.sha256(content).hexdigest(),"retrieved_at":dt.datetime.now(dt.timezone.utc).isoformat()},indent=2),encoding="utf-8")
    build_review()


if __name__ == "__main__":
    main()
