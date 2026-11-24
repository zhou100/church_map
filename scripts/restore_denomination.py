"""Put back the directory denominations the website extractor overwrote (fix plan step 3).

Until migration 0009 the extractor ran `denomination = COALESCE(<model>, denomination)`,
so for crawled churches `churches.denomination` holds the model's reading of the
website instead of the directory's value. The owner accepted the 2026-05 SQLite
snapshot (before v2 extraction ran) as the directory baseline. For every
non-Muse church whose production value differs from that baseline and that the
extractor has touched (extracted_at set), this script:

  * keeps the model's reading as `extracted_denomination` when that is still
    empty (a reading written since 0009 is newer and is kept);
  * restores `denomination` to the baseline value, NULL included ("unknown stays
    unknown").

A difference on a church the extractor never touched has some other writer; it
is counted and left alone. Published Muse congregations (source = 'muse') are the
publisher's and are left alone.

    PUBLISH_DATABASE_URL=... python -m scripts.restore_denomination plan  --sqlite holyhub.db --out DIR
    PUBLISH_DATABASE_URL=... python -m scripts.restore_denomination apply --sqlite holyhub.db --run-dir DIR/<run_id>
    PUBLISH_DATABASE_URL=... python -m scripts.publish_verified --revert <run_id>

`plan` only reads. It writes plan.json and a review CSV (0600) in a private
directory and prints counts. `apply` writes only the reviewed plan: plan.json must
reproduce the reviewed CSV, the baseline file must be the same bytes, and a row
is restored only while its `denomination` is still the reviewed value (others
are counted as skipped). Every write goes to publish_log under the plan's run_id,
so publish_verified --revert undoes it. Output is counts only.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

BATCH = 500
SCOPE_SEED = Path(__file__).resolve().parents[1] / "analytics/dbt/seeds/denomination_scope.csv"
CSV_FIELDS = ["run_id", "church_id", "name", "city", "state", "kind", "baseline", "production",
              "extracted_before", "extracted_after", "baseline_scope", "production_scope"]


def norm(value):
    value = (value or "").strip() if isinstance(value, str) else value
    return value or None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def baseline(sqlite_path: Path) -> dict[int, str | None]:
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        return {int(cid): norm(d) for cid, d in con.execute("select church_id, denomination from churches")}
    finally:
        con.close()


def scope_map() -> dict[str, str]:
    with SCOPE_SEED.open(encoding="utf-8") as f:
        return {r["denomination_key"]: r["scope_status"] for r in csv.DictReader(f)}


def scope_of(denomination, mapping) -> str:
    # int_scope's key: lower(denomination); unmapped is the default in_scope.
    return mapping.get(denomination.lower(), "in_scope") if denomination else "in_scope"


def build(rows, base: dict, mapping: dict) -> tuple[list[dict], dict]:
    """rows: (church_id, name, city, state, source, denomination, extracted_denomination, extracted_at)."""
    counts = {"production_rows": 0, "muse_skipped": 0, "not_in_baseline": 0, "same": 0,
              "untouched_by_extractor": 0, "restore": 0, "restore_to_null": 0,
              "keep_newer_reading": 0, "scope_changes_back": 0}
    plan = []
    for cid, name, city, state, source, denomination, extracted, extracted_at in rows:
        counts["production_rows"] += 1
        if source == "muse":
            counts["muse_skipped"] += 1
            continue
        if cid not in base:
            counts["not_in_baseline"] += 1
            continue
        old, prod = base[cid], norm(denomination)
        if old == prod:
            counts["same"] += 1
            continue
        if extracted_at is None:
            counts["untouched_by_extractor"] += 1
            continue
        counts["restore"] += 1
        counts["restore_to_null"] += old is None
        counts["keep_newer_reading"] += extracted is not None
        before, after = scope_of(prod, mapping), scope_of(old, mapping)
        counts["scope_changes_back"] += before != after
        plan.append({"church_id": cid, "name": name, "city": city, "state": state,
                     "kind": "filled" if old is None else "changed",
                     "baseline": old, "production": denomination,
                     "extracted_before": extracted,
                     "extracted_after": extracted if extracted is not None else denomination,
                     "baseline_scope": after, "production_scope": before})
    return plan, counts


def read_production(prod):
    with prod.cursor() as cur:
        return cur.execute(
            "select church_id, name, city, state, source, denomination, extracted_denomination, extracted_at "
            "from churches order by church_id").fetchall()


def write_csv(path: Path, run_id: str, plan: list[dict]) -> str:
    with path.open("x", newline="", encoding="utf-8") as f:
        os.chmod(path, 0o600)
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        w.writeheader()
        # Scope changes first: those are what the review is for.
        for p in sorted(plan, key=lambda p: (p["baseline_scope"] == p["production_scope"], p["church_id"])):
            w.writerow({"run_id": run_id, **{k: "" if p[k] is None else p[k] for k in CSV_FIELDS[1:]}})
    return sha256(path)


def make_plan(prod, sqlite_path: Path, out: Path) -> dict:
    from scripts import publish_verified as publisher
    publisher.check_visibility(prod)
    base, mapping = baseline(sqlite_path), scope_map()
    plan, counts = build(read_production(prod), base, mapping)
    run_id = "restore-denomination-" + uuid.uuid4().hex[:12]
    run_dir = out / run_id
    run_dir.mkdir(mode=0o700, parents=True)
    csv_sha = write_csv(run_dir / "review.csv", run_id, plan)
    doc = {"run_id": run_id, "review_sha256": csv_sha, "baseline_sha256": sha256(sqlite_path),
           "planned_at": dt.datetime.now(dt.timezone.utc).isoformat(), "counts": counts, "plan": plan}
    path = run_dir / "plan.json"
    with path.open("x", encoding="utf-8") as f:
        os.chmod(path, 0o600)
        json.dump(doc, f, sort_keys=True, indent=1)
    return {"run_id": run_id, "run_dir": str(run_dir), **counts}


def verified_plan(run_dir: Path, sqlite_path: Path) -> dict:
    import tempfile
    doc = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    if sha256(run_dir / "review.csv") != doc["review_sha256"]:
        raise SystemExit("review.csv is not the reviewed file")
    with tempfile.TemporaryDirectory() as tmp:
        if write_csv(Path(tmp) / "again.csv", doc["run_id"], doc["plan"]) != doc["review_sha256"]:
            raise SystemExit("plan.json does not reproduce the reviewed file")
    if sha256(sqlite_path) != doc["baseline_sha256"]:
        raise SystemExit("the baseline snapshot is not the file this plan was made from")
    base = baseline(sqlite_path)
    if any(base.get(p["church_id"], "<missing>") != p["baseline"] for p in doc["plan"]):
        raise SystemExit("plan.json disagrees with the baseline snapshot")
    return doc


def apply(prod, doc: dict) -> dict:
    from scripts import publish_verified as publisher
    publisher.check_schema(prod)
    publisher.check_visibility(prod)
    run_id = doc["run_id"]
    with prod.cursor() as cur:
        if cur.execute("select exists (select 1 from publish_log where run_id = %s)", (run_id,)).fetchone()[0]:
            raise SystemExit(f"{run_id} has already been applied or reverted; make a new plan")
    counts = {"restored": 0, "reading_kept": 0, "skipped_changed_since_review": 0}
    plan = doc["plan"]
    for i in range(0, len(plan), BATCH):
        batch = {p["church_id"]: p for p in plan[i:i + BATCH]}
        with prod.transaction(), prod.cursor() as cur:
            current = {r[0]: r[1:] for r in cur.execute(
                "select church_id, source, denomination, extracted_denomination from churches "
                "where church_id = any(%s) for update", (list(batch),)).fetchall()}
            ids, denominations, readings, log = [], [], [], []
            for cid, p in batch.items():
                source, denomination, extracted = current.get(cid, ("<missing>", None, None))
                if source == "muse" or source == "<missing>" or denomination != p["production"]:
                    counts["skipped_changed_since_review"] += 1
                    continue
                reading = extracted if extracted is not None else denomination
                ids.append(cid)
                denominations.append(p["baseline"])
                readings.append(reading)
                log.append((run_id, cid, "denomination", "update", denomination, p["baseline"]))
                if extracted is None:
                    log.append((run_id, cid, "extracted_denomination", "update", None, denomination))
                else:
                    counts["reading_kept"] += 1
            if ids:
                cur.execute(
                    "update churches c set denomination = v.denomination, extracted_denomination = v.reading "
                    "from unnest(%s::bigint[], %s::text[], %s::text[]) as v(church_id, denomination, reading) "
                    "where c.church_id = v.church_id", (ids, denominations, readings))
                if cur.rowcount != len(ids):
                    raise RuntimeError("update touched an unexpected number of rows")
                cur.executemany("insert into publish_log (run_id, church_id, field, action, old_value, new_value) "
                                "values (%s, %s, %s, %s, %s, %s)", log)
                counts["restored"] += len(ids)
    return {"run_id": run_id, **counts}


def main(argv: list[str] | None = None) -> int:
    import psycopg
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="read production and write the review file (no writes)")
    p.add_argument("--sqlite", type=Path, required=True, help="the accepted 2026-05 baseline snapshot")
    p.add_argument("--out", type=Path, default=Path.home() / "churchmap_private" / "denomination_restore")
    a = sub.add_parser("apply", help="write the reviewed plan to production")
    a.add_argument("--sqlite", type=Path, required=True)
    a.add_argument("--run-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    url = os.environ.get("PUBLISH_DATABASE_URL")
    if not url:
        raise SystemExit("PUBLISH_DATABASE_URL (the publisher role) is not set")
    if args.command == "apply":
        doc = verified_plan(args.run_dir, args.sqlite)
    with psycopg.connect(url, autocommit=True, prepare_threshold=None) as prod:
        if args.command == "plan":
            prod.execute("set session characteristics as transaction read only")
            result = make_plan(prod, args.sqlite, args.out)
        else:
            result = apply(prod, doc)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
