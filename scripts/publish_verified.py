"""Publish the analytics sidecar's verified facts to production (plan workstream B2).

Reads two dbt marts from the analytics database and writes the production
`churches` table (migration 0006):

  * mart_publish_churches: directory churches. The D-1 scope flag, and for
    in-scope churches the facts that pass the display rule, each with its source.
  * mart_publish_new: congregations Muse found, ready for the map. Inserted with
    source = 'muse' and external_id = the candidate ref; a re-run updates them.

Dry run by default: prints a summary and writes analytics/exports/publish_diff_<run>.csv.
Nothing is written to production without --apply.

    DATABASE_URL=<production> python -m scripts.publish_verified            # dry run
    DATABASE_URL=<production> python -m scripts.publish_verified --apply
    DATABASE_URL=<production> python -m scripts.publish_verified --revert <run_id>

Write rules:
  * fill a blank freely; replace a different value only with a verified one (every
    mart value is), logging the old value in publish_log;
  * never blank a field: a NULL in the mart means "write nothing";
  * never write a Facebook URL into `website` (the crawler reads it);
  * one transaction per 50 churches; church_fact_sources gets the source of each
    written fact (no excerpts).

This is an out-of-band script like scripts/migrate_data.py, so it uses psycopg
directly; routers never do.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import math
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / "analytics" / "exports"
ANALYTICS_URL = os.environ.get("ANALYTICS_DATABASE_URL", "postgresql://analytics@localhost:5433/churchmap_analytics")
VERIFIED_BY = "muse+recheck"
BATCH = 50

# Production column -> SQL type, for the fields this script may write.
COLUMNS = {
    "name": "text", "denomination": "text", "address": "text", "city": "text", "state": "text",
    "zip_code": "text", "phone": "text", "service_times": "text", "service_languages": "text",
    "kids_program": "text", "website": "text", "facebook_url": "text",
    "latitude": "double precision", "longitude": "double precision",
    "scope_status": "text", "display_tradition": "text",
    "verified_at": "timestamptz", "verified_by": "text",
}
CHURCH_FIELDS = ["scope_status", "display_tradition", "address", "zip_code", "phone", "service_times",
                 "service_languages", "kids_program", "website", "facebook_url", "latitude", "longitude"]
NEW_FIELDS = ["name", "denomination", "address", "city", "state", "zip_code", "phone", "service_times",
              "service_languages", "kids_program", "website", "facebook_url", "latitude", "longitude"]
# A written fact -> the mart columns holding where it was stated.
SOURCES = {"address": "address", "phone": "phone", "service_times": "service", "kids_program": "kids"}
FACTS = set(CHURCH_FIELDS) - {"scope_status", "display_tradition"}


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _same(old, new, field: str = "") -> bool:
    """Equal for this field: phones by their last 10 digits, URLs ignoring scheme,
    www. and a trailing slash, numbers within 1e-6, text ignoring case and spacing."""
    if field == "phone":
        digits = lambda v: re.sub(r"\D", "", str(v))[-10:]
        if len(digits(old)) == 10 and digits(old) == digits(new):
            return True
    if field in ("website", "facebook_url"):
        url = lambda v: re.sub(r"^(https?://)?(www\.)?", "", str(v).strip().lower()).rstrip("/")
        if url(old) == url(new):
            return True
    if isinstance(new, float) or isinstance(old, float):
        try:
            return math.isclose(float(old), float(new), abs_tol=1e-6)
        except (TypeError, ValueError):
            return False
    norm = lambda v: " ".join(str(v).split()).casefold()
    return norm(old) == norm(new)


def plan_fields(current: dict | None, desired: dict, fields: list[str]) -> list[tuple[str, str, object, object]]:
    """(field, action, old, new) for every field this run would write: 'fill' a blank,
    'replace' a different value. Unchanged, empty and unsafe values are skipped."""
    out = []
    for field in fields:
        new = desired.get(field)
        if _blank(new):
            continue  # never blank a field
        if field == "website" and "facebook.com" in str(new).lower():
            continue  # a Page goes to facebook_url, never into website
        old = (current or {}).get(field)
        if not _blank(old) and _same(old, new, field):
            continue
        out.append((field, "fill" if _blank(old) else "replace", old, new))
    return out


def _text(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, (dt.datetime, dt.date)) else str(value)


def load_marts(con) -> tuple[list[dict], list[dict]]:
    with con.cursor(row_factory=dict_row) as cur:
        churches = cur.execute("select * from analytics.mart_publish_churches order by church_id").fetchall()
        new = cur.execute("select * from analytics.mart_publish_new order by external_id").fetchall()
    return churches, new


def check_schema(prod) -> None:
    have = {r[0] for r in prod.execute(
        "select column_name from information_schema.columns where table_name = 'churches'").fetchall()}
    tables = {r[0] for r in prod.execute(
        "select table_name from information_schema.tables where table_name in ('church_fact_sources', 'publish_log')").fetchall()}
    missing = (set(COLUMNS) - have) | ({"church_fact_sources", "publish_log"} - tables)
    if missing:
        raise SystemExit(f"production is missing {sorted(missing)}: deploy migration 0006 first")


def build_plan(prod, churches: list[dict], new: list[dict]) -> list[dict]:
    """One entry per church to write: kind ('update' / 'insert'), ids, field changes, sources."""
    ids = [c["church_id"] for c in churches]
    cols = ", ".join(["church_id"] + [f for f in COLUMNS if f not in ("verified_at", "verified_by")])
    with prod.cursor(row_factory=dict_row) as cur:
        current = {r["church_id"]: r for r in cur.execute(
            f"select {cols} from churches where church_id = any(%s)", (ids,)).fetchall()}
        muse = {r["external_id"]: r for r in cur.execute(
            f"select external_id, {cols} from churches where source = 'muse'").fetchall()}
    plan = []
    for c in churches:
        if c["church_id"] not in current:
            continue  # not in this production database (a different snapshot); nothing to update
        changes = plan_fields(current[c["church_id"]], c, CHURCH_FIELDS)
        if changes:
            plan.append({"kind": "update", "church_id": c["church_id"], "subject": str(c["church_id"]),
                         "changes": changes, "row": c})
    for n in new:
        existing = muse.get(n["external_id"])
        changes = plan_fields(existing, n, NEW_FIELDS)
        if existing is None:
            plan.append({"kind": "insert", "church_id": None, "subject": n["external_id"], "changes": changes, "row": n})
        elif changes:
            plan.append({"kind": "update", "church_id": existing["church_id"], "subject": n["external_id"],
                         "changes": changes, "row": n})
    return plan


def write_diff(plan: list[dict], run_id: str) -> Path:
    EXPORTS.mkdir(parents=True, exist_ok=True)
    path = EXPORTS / f"publish_diff_{run_id}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["run_id", "kind", "subject", "church_id", "field", "action", "old_value", "new_value"])
        for p in plan:
            for field, action, old, new in p["changes"]:
                w.writerow([run_id, p["kind"], p["subject"], p["church_id"] or "", field, action, _text(old), _text(new)])
    return path


def summarize(plan: list[dict]) -> str:
    kinds = collections.Counter(p["kind"] for p in plan)
    fields = collections.Counter((p["kind"], f, a) for p in plan for f, a, _, _ in p["changes"])
    lines = [f"churches to update: {kinds['update']}; new congregations to insert: {kinds['insert']}"]
    for (kind, field, action), n in sorted(fields.items()):
        lines.append(f"  {kind:6} {field:18} {action:7} {n}")
    return "\n".join(lines)


def _log(cur, run_id, church_id, field, action, old, new) -> None:
    cur.execute("insert into publish_log (run_id, church_id, field, action, old_value, new_value) "
                "values (%s, %s, %s, %s, %s, %s)", (run_id, church_id, field, action, _text(old), _text(new)))


def _sources(cur, run_id: str, church_id: int, row: dict, written: set[str]) -> None:
    """church_fact_sources for the facts written now; for a new congregation also the
    evidence it is active (field 'active')."""
    groups = [(f, g) for f, g in SOURCES.items() if f in written]
    if row.get("status_source_url"):
        groups.append(("active", "status"))
    for field, group in groups:
        url, kind = row.get(f"{group}_source_url"), row.get(f"{group}_source_type")
        if not url:
            continue
        cur.execute(
            "insert into church_fact_sources (church_id, field, source_url, source_type, checked_at, recheck_verdict, run_id) "
            "values (%s, %s, %s, %s, %s, %s, %s) on conflict (church_id, field) do update set "
            "source_url = excluded.source_url, source_type = excluded.source_type, checked_at = excluded.checked_at, "
            "recheck_verdict = excluded.recheck_verdict, run_id = excluded.run_id",
            (church_id, field, url, kind, row.get("checked_at"),
             "facebook_page" if kind == "fb_page" else "verified", run_id))


def apply(prod, plan: list[dict], run_id: str) -> dict:
    counts = collections.Counter()
    for i in range(0, len(plan), BATCH):
        with prod.transaction(), prod.cursor() as cur:
            for p in plan[i:i + BATCH]:
                row, changes = p["row"], p["changes"]
                written = {f for f, _, _, _ in changes}
                stamp = {}
                if written & (FACTS | set(NEW_FIELDS)) and row.get("checked_at"):
                    stamp = {"verified_at": row["checked_at"], "verified_by": VERIFIED_BY}
                if p["kind"] == "insert":
                    values = {f: new for f, _, _, new in changes} | stamp | {"source": "muse", "external_id": row["external_id"]}
                    cols = list(values)
                    cur.execute(f"insert into churches ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
                                "returning church_id", [values[c] for c in cols])
                    church_id = cur.fetchone()[0]
                    _log(cur, run_id, church_id, "*", "insert", None, row["external_id"])
                    counts["inserted"] += 1
                else:
                    church_id = p["church_id"]
                    if stamp:
                        old_stamp = cur.execute("select verified_at, verified_by from churches where church_id = %s",
                                                (church_id,)).fetchone()
                        changes = changes + [("verified_at", "stamp", old_stamp[0], stamp["verified_at"]),
                                             ("verified_by", "stamp", old_stamp[1], stamp["verified_by"])]
                    sets = ", ".join(f"{f} = %s" for f, _, _, _ in changes)
                    cur.execute(f"update churches set {sets} where church_id = %s",
                                [new for _, _, _, new in changes] + [church_id])
                    for f, _, old, new in changes:
                        _log(cur, run_id, church_id, f, "update", old, new)
                    counts["updated"] += 1
                _sources(cur, run_id, church_id, row, written)
    return dict(counts)


def revert(prod, run_id: str) -> dict:
    """Restore every value the run changed (latest first), delete the congregations it
    inserted, and drop the fact sources it wrote."""
    counts = collections.Counter()
    with prod.transaction(), prod.cursor() as cur:
        rows = cur.execute("select church_id, field, action, old_value from publish_log "
                           "where run_id = %s and action in ('update', 'insert') order by id desc", (run_id,)).fetchall()
        if not rows:
            raise SystemExit(f"no publish_log rows for run {run_id}")
        for church_id, field, action, old in rows:
            if action == "insert":
                cur.execute("delete from churches where church_id = %s and source = 'muse'", (church_id,))
                counts["deleted"] += 1
            else:
                cur.execute(f"update churches set {field} = %s::{COLUMNS[field]} where church_id = %s", (old, church_id))
                counts["restored"] += 1
        cur.execute("delete from church_fact_sources where run_id = %s", (run_id,))
        cur.execute("insert into publish_log (run_id, church_id, field, action) values (%s, 0, '*', 'revert')", (run_id,))
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write to production (default: dry run)")
    mode.add_argument("--revert", metavar="RUN_ID", help="undo a run")
    args = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL (production) is not set")
    # autocommit: each prod.transaction() block below is its own transaction (one per
    # 50 churches), not a savepoint of one long implicit transaction.
    # prepare_threshold=None: required by Supabase's transaction pooler (port 6543).
    with psycopg.connect(url, autocommit=True, prepare_threshold=None) as prod:
        check_schema(prod)
        if args.revert:
            print(f"reverted {args.revert}: {revert(prod, args.revert)}")
            return 0
        with psycopg.connect(ANALYTICS_URL) as ana:
            churches, new = load_marts(ana)
        run_id = "pub-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        plan = build_plan(prod, churches, new)
        diff = write_diff(plan, run_id)
        print(f"{'APPLY' if args.apply else 'DRY RUN'} {run_id}: marts {len(churches)} churches, {len(new)} new\n"
              f"{summarize(plan)}\ndiff: {diff}")
        if args.apply:
            print(f"applied {run_id}: {apply(prod, plan, run_id)} (undo: --revert {run_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
