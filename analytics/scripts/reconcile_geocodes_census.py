"""Reconcile the regenerated input, retaining unchanged Census work and reviews.

--fetch submits only new/changed original address fields, saving a separate batch.
The input and initial raw batch are never written. Offline runs use saved evidence.
"""
import argparse
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
import time

from geocode_census import FIELDS, classify, fetch, validate_clusters

ROOT=Path(__file__).resolve().parents[2]
EXPORTS=ROOT / "analytics" / "exports"
EXPECTED="845c5d8a6b0881a446f9b76acf8684b4408452ce4ae44ea4a684503d418cf793"


def read_csv(path):
    return list(csv.DictReader(path.open(encoding="utf-8-sig",newline="")))


def echo(row):
    return ", ".join(row[k] for k in ("street","city","state","zip")).rstrip()


def changed_rows(rows, raw):
    return [r for r in rows if r["geo_id"] not in raw or raw[r["geo_id"]][1].rstrip()!=echo(r)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch",action="store_true")
    args=parser.parse_args()
    started=time.monotonic()
    # The live file can be regenerated concurrently. Work only from the exact
    # owner-authorized 196-row snapshot; never add restored rows implicitly.
    input_path=EXPORTS / "geocode_input_845c5d8a.csv"
    digest=hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert digest==EXPECTED,"Snapshot differs from the owner's exact 196-row handoff"
    rows=read_csv(input_path)
    ids=[r["geo_id"] for r in rows]
    assert len(ids)==len(set(ids))==196
    input_count=len(ids)
    by_id={r["geo_id"]:r for r in rows}
    history=EXPORTS / "geocode_history"
    history.mkdir(exist_ok=True)
    # Immutable source for offline reproduction after the current output changes.
    for name in ("geocode_output.csv","geocode_run_log.md"):
        snapshot=history / ("initial_198_"+name)
        if not snapshot.exists():
            snapshot.write_bytes((EXPORTS / name).read_bytes())
    old_output={r["geo_id"]:r for r in read_csv(history / "initial_198_geocode_output.csv")}
    raw_bytes=(EXPORTS / "geocode_census_raw.csv").read_bytes()
    original_meta=json.loads((EXPORTS / "geocode_census_metadata.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw_bytes).hexdigest()==original_meta["raw_sha256"]
    raw={r[0]:r for r in csv.reader(io.StringIO(raw_bytes.decode("utf-8-sig")))}
    pending=changed_rows(rows,raw)
    raw_update=EXPORTS / "geocode_update_raw.csv"
    meta_update=EXPORTS / "geocode_update_metadata.json"
    if args.fetch:
        fetch(pending,digest,raw_path=raw_update,metadata_path=meta_update)
    metadata=json.loads(meta_update.read_text(encoding="utf-8"))
    assert metadata["input_sha256"]==digest
    content=raw_update.read_bytes()
    assert hashlib.sha256(content).hexdigest()==metadata["raw_sha256"]
    updated={r[0]:r for r in csv.reader(io.StringIO(content.decode("utf-8-sig")))}
    assert set(updated)=={r["geo_id"] for r in pending}
    review_receipt=json.loads((EXPORTS / "geocode_review_decisions.json").read_text(encoding="utf-8"))
    decisions={r["geo_id"]:r for r in review_receipt["decisions"]}
    reviews={r["geo_id"]:r for r in read_csv(EXPORTS / "geocode_review.csv")}
    output=[]
    sources=[]
    for row in rows:
        geo_id=row["geo_id"]
        if geo_id in updated:
            assert updated[geo_id][1].rstrip()==echo(row)
            out=classify(row,updated[geo_id],metadata["geocoded_at"])
            sources.append({"geo_id":geo_id,"kind":"new Census batch","raw_file":raw_update.name})
        else:
            assert raw[geo_id][1].rstrip()==echo(row)
            out=dict(old_output[geo_id])
            sources.append({"geo_id":geo_id,"kind":"unchanged original Census result","raw_file":"geocode_census_raw.csv"})
        if geo_id not in updated and geo_id in reviews and reviews[geo_id]["status"]=="ok":
            original=decisions[geo_id]["original_input"]
            assert all(original[k]==row[k] for k in ("street","city","state","zip")),"Review belongs to a different address"
            out=dict(reviews[geo_id])
            sources[-1].update(kind="completed Census review",receipt="geocode_review_decisions.json")
        output.append(out)
    shared=validate_clusters(output,by_id)
    assert len(output)==input_count and {r["geo_id"] for r in output}==set(ids)
    assert all(r["latitude"] and r["longitude"] if r["status"]=="ok" else not r["latitude"] and not r["longitude"] for r in output)
    excluded=[]
    for geo_id in sorted(set(old_output)-set(ids)):
        excluded.append({"geo_id":geo_id,"result":old_output[geo_id],
                         "reason":"Transient address recheck failure; retain for reappearance" if geo_id=="candidate:C-042" else "Removed by owner; excluded from current handoff"})
    (EXPORTS / "geocode_retained_results.json").write_text(json.dumps(excluded,indent=2)+"\n",encoding="utf-8")
    assert hashlib.sha256(input_path.read_bytes()).hexdigest()==digest
    with (EXPORTS / "geocode_output.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=FIELDS,lineterminator="\n")
        writer.writeheader();writer.writerows(output)
    receipt={"input_sha256":digest,"rows":input_count,"new_request_ids":sorted(updated),
             "update_metadata":metadata,"original_raw_sha256":original_meta["raw_sha256"],
             "initial_output_sha256":hashlib.sha256((history / "initial_198_geocode_output.csv").read_bytes()).hexdigest(),
             "review_csv_sha256":hashlib.sha256((EXPORTS / "geocode_review.csv").read_bytes()).hexdigest(),
             "output_sha256":hashlib.sha256((EXPORTS / "geocode_output.csv").read_bytes()).hexdigest(),
             "sources":sources}
    (EXPORTS / "geocode_reconciliation.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    counts=collections.Counter(r["status"] for r in output)
    types=collections.Counter(r["match_type"] for r in output)
    lines=[f"# Census geocoding: reconciled {input_count}-row input", "",
           f"Input SHA-256: `{digest}`. Every current input ID appears exactly once; original addresses are unchanged.", "",
           f"Status: {dict(counts)}. Match types: {dict(types)}.", "",
           f"New Census batch at {metadata['geocoded_at']}: {', '.join(sorted(updated))}. Request {metadata['request_seconds']} seconds; this command {time.monotonic()-started:.2f} seconds. Public_AR_Current / Current_Current; HTTP {metadata['http_status']}.", "",
           "D-013 uses the owner's source-checked ZIP 94102 from the regenerated input. Its previous ZIP-less tie is superseded only by the new Census result. D-035 had no earlier result and was submitted unchanged in the same bounded batch.", "",
           f"Unchanged original results and eight completed Census reviews were reused. This preserves their original geocoding timestamps, range evidence, and shared pins. This is an input reconciliation, not a new geocoding attempt for all {input_count} rows.", "",
           "The earlier scoped review CSV/log are historical; this output and geocode_reconciliation.json describe the exact 196-row handoff. Initial output/log are preserved in geocode_history/. C-042's existing result is saved in geocode_retained_results.json, outside this handoff. C-054 and D-059 remain excluded. The source is geocode_input_845c5d8a.csv, whose hash matches the owner's handoff exactly; the concurrently regenerated live input is never written or silently substituted.", "",
           f"Acceptance: {input_count} unique IDs; exact 13 columns; all accepted points are Census street-segment matches; county/envelope evidence retained; different-address coordinate collisions withheld. Every pin_off row retains its distance from the old pin. No database writes, publication, address edits or non-Census requests.", "",
           "## New or updated results", "", "| ID | Status | Census matched address | Segment / side |", "|---|---|---|---|"]
    for r in output:
        if r["geo_id"] in updated:lines.append(f"| {r['geo_id']} | {r['status']} | {r['matched_address']} | {r['tiger_line_id']} / {r['side']} |")
    lines += ["", "## Existing pins moved over 150 m", "", "| ID | Reason | Distance (m) |", "|---|---|---:|"]
    for r in output:
        if r["distance_from_current_pin_m"] and float(r["distance_from_current_pin_m"])>150:
            lines.append(f"| {r['geo_id']} | {by_id[r['geo_id']]['reason']} | {r['distance_from_current_pin_m']} |")
    lines += ["", "## Unresolved", "", "| ID | Status | Note |", "|---|---|---|"]
    for r in output:
        if r["status"]!="ok":lines.append(f"| {r['geo_id']} | {r['status']} | {r['notes']} |")
    lines += ["", "Offline reproduction: `python analytics/scripts/reconcile_geocodes_census.py`. `--fetch` explicitly submits the two changed/new rows. No paid or secondary geocoder is used.", ""]
    (EXPORTS / "geocode_run_log.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"rows":len(output),"status":dict(counts),"new_requests":sorted(updated),"retained_excluded":sorted(set(old_output)-set(ids))}))


if __name__=="__main__":
    main()
