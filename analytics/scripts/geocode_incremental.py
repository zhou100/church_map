"""Incremental Census geocoding: submit only addresses without a result yet.

Every result is kept in a ledger keyed by (geo_id, street, city, state, zip). A row
whose exact address already has a result reuses it (Census runs, reviews); a new row
or a corrected address is submitted in one Census batch. Never changes addresses or
writes a database other than reading the analytics sidecar.

  python analytics/scripts/geocode_incremental.py            # report what is pending
  python analytics/scripts/geocode_incremental.py --fetch    # submit pending rows, write output

Output: geocode_output.csv for the whole input, plus geocode_reconciliation.json
binding it to the input snapshot geocode_input_<sha8>.csv (read by build_seeds.py).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

from geocode_census import EXPORTS, FIELDS, classify, fetch, validate_clusters

LEDGER = EXPORTS / "geocode_ledger.csv"
HISTORY = EXPORTS / "geocode_history"
RECEIPT = EXPORTS / "geocode_reconciliation.json"
OUTPUT = EXPORTS / "geocode_output.csv"
ADDRESS = ("street", "city", "state", "zip")
INPUT_COLS = ["geo_id", "name", "street", "city", "state", "zip",
              "current_lat", "current_lon", "reason", "profile_ready"]
LEDGER_COLS = ["geo_id", *ADDRESS, *FIELDS[1:], "source"]
DEFAULT_URL = "postgresql://analytics@localhost:5433/churchmap_analytics"
# docs/plans/geocode_and_publish_plan.md, appendix: every verified address that needs a pin.
INPUT_SQL = """
  select 'candidate:'||candidate_id as geo_id, candidate_name as name, display_street_address as street,
         city, 'CA' as state, display_zip as zip, null::float8 as current_lat, null::float8 as current_lon,
         'new_congregation' as reason, profile_ready
    from analytics.mart_new_congregations where address_displayable
  union all
  select 'church:'||d.church_id, d.display_name, d.display_street_address, d.city, coalesce(d.state,'CA'),
         d.display_zip, d.latitude, d.longitude,
         case when r.pin_check = 'off' then 'pin_off' else 'verify_pin' end, d.visit_ready
    from analytics.dim_church d join analytics.int_location_readiness r using (church_id)
   where r.address_displayable and coalesce(r.pin_check, 'unknown') in ('off', 'unknown')
  order by 1
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def key(row: dict) -> tuple:
    return (row["geo_id"], *(row[k] or "" for k in ADDRESS))


def echo(row: dict) -> str:
    return ", ".join(row[k] or "" for k in ADDRESS).rstrip()


def cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "t" if value else "f"
    return str(value)


def export_input() -> Path:
    """Write the current input from dbt as geocode_input_<sha8>.csv; return its path."""
    import psycopg
    with psycopg.connect(os.environ.get("ANALYTICS_DATABASE_URL", DEFAULT_URL)) as con:
        rows = con.execute(INPUT_SQL).fetchall()
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(INPUT_COLS)
    writer.writerows([cell(v) for v in r] for r in rows)
    content = buf.getvalue().encode("utf-8")
    path = EXPORTS / f"geocode_input_{hashlib.sha256(content).hexdigest()[:8]}.csv"
    if not path.exists():
        path.write_bytes(content)
    return path


def bound_input() -> Path | None:
    """The input the current geocode_output.csv was made from (same rule as build_seeds):
    only a receipt naming this exact output binds it. No fallback."""
    digest = None
    if OUTPUT.exists() and RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        if receipt.get("output_sha256") == sha256(OUTPUT):
            digest = receipt["input_sha256"]
    return next((p for p in sorted(EXPORTS.glob("geocode_input*.csv")) if digest and sha256(p) == digest), None)


def publish(output: list[dict], receipt: dict) -> None:
    """Write output and receipt as one step: both go to temp files first, then replace.
    An interruption between the two replaces leaves a receipt that names another
    output, which build_seeds rejects (no pins) instead of mislabeling them."""
    tmp_out, tmp_receipt = OUTPUT.with_suffix(".csv.tmp"), RECEIPT.with_suffix(".json.tmp")
    write_csv(tmp_out, FIELDS, output)
    receipt = {**receipt, "output_sha256": sha256(tmp_out)}
    tmp_receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_out, OUTPUT)
    os.replace(tmp_receipt, RECEIPT)


def seed_ledger() -> list[dict]:
    """First run: every result in the current output, bound to the address it was made from."""
    source = bound_input()
    if source is None:
        raise SystemExit("geocode_output.csv has no input with its recorded sha256; can't seed the ledger")
    asked = {r["geo_id"]: r for r in read_csv(source)}
    return [{**{k: asked[r["geo_id"]][k] for k in ADDRESS}, **r, "source": f"seed:{source.name}"}
            for r in read_csv(OUTPUT) if r["geo_id"] in asked]


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fetch", action="store_true", help="submit pending addresses to Census")
    ap.add_argument("--input", type=Path, help="use this input file instead of exporting from dbt")
    ap.add_argument("--reclassify", metavar="RAW", help="re-apply classify() to the ledger rows from this "
                    "saved batch in geocode_history/ (after a rule change; nothing is resubmitted)")
    args = ap.parse_args()
    started = time.monotonic()

    input_path = args.input or export_input()
    digest = sha256(input_path)
    rows = read_csv(input_path)
    ids = [r["geo_id"] for r in rows]
    assert len(ids) == len(set(ids)), "Duplicate input IDs"
    ledger = read_csv(LEDGER) if LEDGER.exists() else seed_ledger()
    if args.reclassify:
        raw_path = HISTORY / args.reclassify
        meta = json.loads(raw_path.with_name(raw_path.name.replace("_raw.csv", "_meta.json")).read_text(encoding="utf-8"))
        assert sha256(raw_path) == meta["raw_sha256"]
        raw = {r[0]: r for r in csv.reader(io.StringIO(raw_path.read_text(encoding="utf-8-sig")))}
        current = {r["geo_id"]: r for r in rows}
        for i, entry in enumerate(ledger):
            if entry["source"] == raw_path.name:
                assert raw[entry["geo_id"]][1].rstrip() == echo(entry)
                ask = {**entry, "current_lat": "", "current_lon": ""}
                if entry["geo_id"] in current and key(current[entry["geo_id"]]) == key(entry):
                    ask.update({k: current[entry["geo_id"]][k] for k in ("current_lat", "current_lon")})
                ledger[i] = {**entry, **classify(ask, raw[entry["geo_id"]], meta["geocoded_at"])}
        write_csv(LEDGER, LEDGER_COLS, ledger)
    known = {key(r): r for r in ledger}
    pending = [r for r in rows if key(r) not in known]
    print(f"{input_path.name}: {len(rows)} rows, {len(rows) - len(pending)} with a result, {len(pending)} pending")
    if pending and not args.fetch:
        print("run with --fetch to submit them to Census")
        return 1

    batch = None
    if pending:
        HISTORY.mkdir(exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        raw_path, meta_path = HISTORY / f"census_{stamp}_raw.csv", HISTORY / f"census_{stamp}_meta.json"
        fetch(pending, digest, raw_path=raw_path, metadata_path=meta_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw = {r[0]: r for r in csv.reader(io.StringIO(raw_path.read_text(encoding="utf-8-sig")))}
        for row in pending:
            assert raw[row["geo_id"]][1].rstrip() == echo(row), f"Census echoed a different address: {row['geo_id']}"
            out = classify(row, raw[row["geo_id"]], meta["geocoded_at"])
            entry = {**{k: row[k] for k in ADDRESS}, **out, "source": raw_path.name}
            ledger.append(entry)
            known[key(row)] = entry
        write_csv(LEDGER, LEDGER_COLS, ledger)  # results are kept before anything else can fail
        batch = {"raw_file": raw_path.name, "metadata": meta, "ids": sorted(r["geo_id"] for r in pending)}
    elif not LEDGER.exists():
        write_csv(LEDGER, LEDGER_COLS, ledger)

    output = [{k: known[key(r)][k] for k in FIELDS} for r in rows]
    shared = validate_clusters(output, {r["geo_id"]: r for r in rows})
    assert all(bool(o["latitude"]) == (o["status"] == "ok") for o in output)
    assert sha256(input_path) == digest
    publish(output, {"input_sha256": digest, "input_file": input_path.name, "rows": len(rows),
                     "ledger_sha256": sha256(LEDGER),
                     "new_request_ids": batch["ids"] if batch else [], "batch": batch,
                     "sources": dict(collections.Counter(known[key(r)]["source"] for r in rows))})

    by_id = {r["geo_id"]: r for r in rows}
    counts = collections.Counter(o["status"] for o in output)
    new = [o for o in output if batch and o["geo_id"] in batch["ids"]]
    log = [f"# Census geocoding: incremental run over a {len(rows)}-row input", "",
           f"- Input `{input_path.name}`, SHA-256 `{digest}`. Addresses are submitted unchanged.",
           f"- Status: {dict(sorted(counts.items()))}. Same-address shared pins: {len(shared)}.",
           f"- Reused from the ledger: {len(rows) - len(new)}. New Census batch: {len(new)} rows"
           + (f" (`{batch['raw_file']}`, HTTP {batch['metadata']['http_status']}, {batch['metadata']['request_seconds']} s)." if batch else "."),
           f"- Command: {time.monotonic() - started:.2f} s. Census only; no database writes or address edits.",
           "", "## New results", "", "| ID | Status | Census matched address | Note |", "|---|---|---|---|"]
    log += [f"| {o['geo_id']} | {o['status']} | {o['matched_address']} | {o['notes']} |" for o in new]
    log += ["", "## Existing pins moved over 150 m", "", "| ID | Reason | Distance (m) |", "|---|---|---:|"]
    log += [f"| {o['geo_id']} | {by_id[o['geo_id']]['reason']} | {o['distance_from_current_pin_m']} |"
            for o in output if o["distance_from_current_pin_m"] and float(o["distance_from_current_pin_m"]) > 150]
    log += ["", "## Unresolved", "", "| ID | Status | Note |", "|---|---|---|"]
    log += [f"| {o['geo_id']} | {o['status']} | {o['notes']} |" for o in output if o["status"] != "ok"]
    log += ["", "Offline reproduction: `python analytics/scripts/geocode_incremental.py --input "
            f"analytics/exports/{input_path.name}` rebuilds this output from the ledger.", ""]
    (EXPORTS / "geocode_run_log.md").write_text("\n".join(log), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "status": dict(counts), "new_requests": len(new)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
