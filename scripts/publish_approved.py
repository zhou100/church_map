"""Publish the new congregations the owner approved from one reviewed dry run.

The shadow run's dry run (scripts/publish_gate.py) leaves a private directory
with the reviewed diff, rows.json (the gate's decisions), run.json and plan.json
(the exact plan behind that diff, mart rows and sources included). This script
publishes an approved part of it without rebuilding the marts:

    python -m scripts.publish_approved approve --run-dir DIR --sections A,B,C
    PUBLISH_DATABASE_URL=... BACKEND_URL=... python -m scripts.publish_approved apply --run-dir DIR
    PUBLISH_DATABASE_URL=... BACKEND_URL=... python -m scripts.publish_approved apply --run-dir DIR --apply
    PUBLISH_DATABASE_URL=... python -m scripts.publish_verified --revert <run_id>

Sections, as in the owner's review list: A = a new congregation with no row-level
gate reason, B = only a low match confidence, C = shares an address with another
new one in the same run (with or without B). Only new congregations can be
approved here; updates to existing churches (replacements, D-1 scope writes) stay
with publish_verified's full review.

`apply` writes nothing unless every check passes:
  * plan.json, rows.json, run.json, approval.json and the diff name one run, and
    plan.json regenerates the reviewed diff byte for byte;
  * the dry run is recent (--max-age-hours) and production has published nothing
    since it (publish_log unchanged apart from this run's own rows);
  * production is not READ_ONLY;
  * each approved congregation is either new, or already inserted by this run
    (a resumed apply skips it), and the publisher plans the same fields today.
The run keeps the reviewed run_id, so publish_log ties every write to the diff
the owner approved, and publish_verified --revert undoes it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

from scripts import publish_verified as publisher

SECTION_REASONS = {"low_match_confidence", "shared_address"}
# Run-level reasons an owner approval cannot override.
BLOCKING = {"dbt_not_passed", "read_only", "health_unavailable", "revert_since_publish"}
D1_FIELDS = {"scope_status", "display_tradition"}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(data: bytes) -> str:
    from scripts.muse_state_store import digest
    return digest(data)


def section(row: dict, run_reasons: set[str]) -> str | None:
    """The review section of one gate decision, or None if it cannot be approved here."""
    own = set(row["reasons"]) - run_reasons
    if row["kind"] != "insert" or not own <= SECTION_REASONS:
        return None
    if any(f in D1_FIELDS for f, *_ in row["changes"]):
        return None
    if "shared_address" in own:
        return "C"
    return "B" if own else "A"


def approve(run_dir: Path, sections: set[str]) -> dict:
    run, rows = _load(run_dir / "run.json"), _load(run_dir / "rows.json")
    if run["run_id"] != rows["run_id"] or run["diff_sha256"] != rows["diff_sha256"]:
        raise SystemExit("run.json and rows.json describe different runs")
    run_reasons = set(run["run_reasons"])
    if run_reasons & BLOCKING:
        raise SystemExit(f"this run cannot be approved: {sorted(run_reasons & BLOCKING)}")
    picked = {}
    for row in rows["rows"]:
        s = section(row, run_reasons)
        if s in sections:
            picked[row["subject"]] = s
    counts = {s: sum(v == s for v in picked.values()) for s in sorted(sections)}
    approval = {"run_id": run["run_id"], "diff_sha256": run["diff_sha256"], "sections": sorted(sections),
                "subjects": sorted(picked), "counts": counts,
                "approved_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    path = run_dir / "approval.json"
    with path.open("x", encoding="utf-8") as out:
        os.chmod(path, 0o600)
        json.dump(approval, out, sort_keys=True, indent=2)
    return {"run_id": run["run_id"], "approved": len(picked), **counts}


def _changes(entry: dict) -> list[tuple]:
    return [tuple(c) for c in entry["changes"]]


def verified_entries(run_dir: Path, max_age_hours: float, now: dt.datetime | None = None) -> tuple[dict, list[dict]]:
    """The approved plan entries, after checking that every file names the reviewed diff."""
    run, rows, plan, approval = (_load(run_dir / n) for n in ("run.json", "rows.json", "plan.json", "approval.json"))
    run_id, sha = run["run_id"], run["diff_sha256"]
    if any(d["run_id"] != run_id or d["diff_sha256"] != sha for d in (rows, plan, approval)):
        raise SystemExit("run, rows, plan and approval do not describe the same reviewed diff")
    diff = run_dir / f"publish_diff_{run_id}.csv"
    if _digest(diff.read_bytes()) != sha:
        raise SystemExit("the diff on disk is not the reviewed diff")
    entries = [{**e, "changes": _changes(e)} for e in plan["plan"]]
    with tempfile.TemporaryDirectory() as tmp:
        again = publisher.write_diff(entries, run_id, Path(tmp))
        if _digest(again.read_bytes()) != sha:
            raise SystemExit("plan.json does not reproduce the reviewed diff")
    observed = dt.datetime.fromisoformat(run["observed_at"])
    age = (now or dt.datetime.now(dt.timezone.utc)) - observed
    if age > dt.timedelta(hours=max_age_hours):
        raise SystemExit(f"the dry run is {age} old; run a new one and review it")
    run_reasons = set(run["run_reasons"])
    if run_reasons & BLOCKING:
        raise SystemExit(f"this run cannot be applied: {sorted(run_reasons & BLOCKING)}")
    decisions = {r["subject"]: r for r in rows["rows"]}
    by_subject = {e["subject"]: e for e in entries}
    approved = []
    for subject in approval["subjects"]:
        entry, decision = by_subject.get(subject), decisions.get(subject)
        if entry is None or decision is None:
            raise SystemExit(f"approved subject {subject} is not in the reviewed run")
        if section(decision, run_reasons) not in set(approval["sections"]):
            raise SystemExit(f"approved subject {subject} is not in an approved section")
        if _changes(decision) != entry["changes"]:
            raise SystemExit(f"{subject}: the gate decision and the plan disagree")
        approved.append(entry)
    return run, approved


def check_production(prod, run: dict, approved: list[dict]) -> tuple[list[dict], int]:
    """Entries still to insert, and how many this run already inserted."""
    publisher.check_schema(prod)
    publisher.check_visibility(prod)
    with prod.cursor() as cur:
        logs = cur.execute("select id, action, run_id from publish_log order by id").fetchall()
        reviewed = {r["id"]: r["action"] for r in run["publish_log"]}
        others = {i: a for i, a, rid in logs if rid != run["run_id"]}
        if others != reviewed:
            raise SystemExit("production has published or reverted since this dry run; run a new one and review it")
        if any(rid == run["run_id"] and a == "revert" for _, a, rid in logs):
            raise SystemExit("this run was reverted; run a new dry run and review it")
        mine = {r[0] for r in cur.execute(
            "select church_id from publish_log where run_id = %s and action = 'insert'", (run["run_id"],)).fetchall()}
        muse = dict(cur.execute("select external_id, church_id from churches where source = 'muse'").fetchall())
    todo, done = [], 0
    for entry in approved:
        row = entry["row"]
        if entry["kind"] != "insert" or entry["church_id"] is not None:
            raise SystemExit(f"{entry['subject']}: only new congregations can be published here")
        if row["external_id"] in muse:
            if muse[row["external_id"]] in mine:
                done += 1
                continue
            raise SystemExit(f"{entry['subject']} is already published by another run")
        if publisher.plan_fields(None, row, publisher.NEW_FIELDS) != entry["changes"]:
            raise SystemExit(f"{entry['subject']}: the publisher would write different fields today")
        todo.append(entry)
    return todo, done


def apply_approved(run_dir: Path, url: str, write: bool, max_age_hours: float) -> dict:
    import psycopg
    from scripts.publish_gate import fetch_health
    run, approved = verified_entries(run_dir, max_age_hours)
    health = fetch_health(os.environ.get("BACKEND_URL", ""))
    if not isinstance(health, dict) or health.get("read_only") is not False:
        raise SystemExit("production health is unavailable or READ_ONLY")
    with psycopg.connect(url, autocommit=True, prepare_threshold=None) as prod:
        todo, done = check_production(prod, run, approved)
        counts = {"approved": len(approved), "already_inserted": done, "to_insert": len(todo)}
        if write and todo:
            counts.update(publisher.apply(prod, todo, run["run_id"]))
    if write:
        receipt = run_dir / f"apply-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S.%fZ}.json"
        with receipt.open("x", encoding="utf-8") as out:
            os.chmod(receipt, 0o600)
            json.dump({"run_id": run["run_id"], **counts}, out, sort_keys=True, indent=2)
    return {"run_id": run["run_id"], "mode": "apply" if write else "dry_run", **counts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("approve", help="record the owner's approval of whole review sections")
    a.add_argument("--run-dir", type=Path, required=True)
    a.add_argument("--sections", required=True, help="comma-separated, e.g. A,B,C")
    p = sub.add_parser("apply", help="check (default) or publish the approved congregations")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--apply", action="store_true", help="write to production (default: checks only)")
    p.add_argument("--max-age-hours", type=float, default=96)
    args = ap.parse_args(argv)
    if args.command == "approve":
        sections = {s.strip().upper() for s in args.sections.split(",") if s.strip()}
        if not sections or not sections <= {"A", "B", "C"}:
            raise SystemExit("sections must be among A, B, C")
        print(json.dumps(approve(args.run_dir, sections), sort_keys=True))
        return 0
    url = os.environ.get("PUBLISH_DATABASE_URL")
    if not url:
        raise SystemExit("PUBLISH_DATABASE_URL (the publisher role) is not set")
    print(json.dumps(apply_approved(args.run_dir, url, args.apply, args.max_age_hours), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
