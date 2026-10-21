"""Work queue between ChurchMap and Muse through a shared Google Drive folder.

Muse has no API, but it reads and writes a Drive folder that Google Drive for
desktop mirrors locally (default /mnt/f/My Drive/churchmap-handoff; override with
CHURCHMAP_DRIVE). The protocol is in drive/README_FOR_MUSE.md. In short: we write
outbox/WP-xxxx/, status.csv, feedback/ and reference/; Muse writes only
returns/WP-xxxx/, and writes DONE.md (file names + sha256) last.

    python3 muse_handoff/drive_sync.py status
    python3 muse_handoff/drive_sync.py new-discovery --title "Marin County" --state CA \\
        --cities "San Rafael=25,Novato=20,Mill Valley=15" --other "Any other Marin County city=10"
    python3 muse_handoff/drive_sync.py new-leads --title "Bay Area IRS leads" --state CA \\
        --leads muse_handoff/outbox/irs_leads_bay_sample100.csv      # from analytics/scripts/irs_leads.py
    python3 muse_handoff/drive_sync.py new-service-fixes --title "Re-quote 20 schedules" --ids 76632,C-063
    python3 muse_handoff/drive_sync.py publish WP-0001
    python3 muse_handoff/drive_sync.py pull [--no-recheck] [--no-build]

pull copies each newly delivered package into muse_handoff/returns/ as
<kind>_WP0001.csv (build_seeds.py picks those up), records when it arrived in
returns/received.csv, validates it, re-checks its sources, and rebuilds seeds and
dbt. A package that fails validation is not ingested: it goes back to Muse as
feedback/WP-xxxx.md with state needs_fix.

Packages, returns and the known list are built from Muse-derived data and stay
gitignored (muse_handoff/outbox/, muse_handoff/returns/).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HANDOFF = Path(__file__).resolve().parent
ROOT = HANDOFF.parent
DRIVE = Path(os.environ.get("CHURCHMAP_DRIVE", "/mnt/f/My Drive/churchmap-handoff"))
OUTBOX = HANDOFF / "outbox"
RET = HANDOFF / "returns"
STATUS = OUTBOX / "status.csv"  # master copy; mirrored read-only to the Drive root
STATUS_COLS = ["wp_id", "title", "state", "published_at", "started_at", "delivered_at", "ingested_at",
               "done_sha256", "note", "build_error"]
RECEIVED_COLS = ["file", "wp_id", "received_at", "done_sha256"]
LATE_STAMP = "is after the file was received"

# What Muse returns (name inside returns/WP-xxxx/) -> local kind (<kind>_WP0001.csv).
OUTPUT_KINDS = {"results.csv": "results", "new_candidates.csv": "new_candidates",
                "service_fixes.csv": "service_fixes", "worship_location.csv": "worship_location",
                "lead_outcomes.csv": "lead_outcomes"}
RECHECKED = {"results", "new_candidates", "service_fixes", "worship_location"}  # files that cite sources
LEAD_OUTCOMES = {"active", "closed", "no_trace", "not_a_congregation", "out_of_scope", "already_known"}
LEAD_COLS = ["lead_id", "ein", "irs_name", "irs_street", "irs_city", "irs_zip", "ruling_year"]
OUTCOME_COLS = ["lead_id", "outcome", "known_id", "evidence_url", "evidence_type", "meets_at_irs_address",
                "checked_at", "minutes_spent", "notes"]
REFERENCE = ["BRIEF_v3.md", "results_TEMPLATE_v3.csv", "new_candidates_TEMPLATE_v3.csv",
             "service_fixes_S_TEMPLATE.csv", "worship_location_W_TEMPLATE.csv", "validate_returns.py"]
KNOWN_COLS = ["known_id", "kind", "name", "current_name", "city", "street_address", "website",
              "facebook_page_url", "note"]

WP_RE = re.compile(r"^WP-(\d{4})$")
SHA_RE = re.compile(r"\b([0-9a-f]{64})\b")
BBOX_MARGIN = 0.03  # degrees (~3 km) around the directory pins of the named cities


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    """Write via a temp file and rename, so Drive never syncs a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def copy_if_changed(src: Path, dst: Path) -> bool:
    if dst.exists() and sha256(dst) == sha256(src):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    tmp.replace(dst)
    return True


# ---------------------------------------------------------------- status

def load_status() -> dict[str, dict]:
    return {r["wp_id"]: r for r in read_csv(STATUS)}


def save_status(status: dict[str, dict]) -> None:
    rows = sorted(status.values(), key=lambda r: r["wp_id"])
    write_csv(STATUS, STATUS_COLS, rows)
    if DRIVE.exists():
        copy_if_changed(STATUS, DRIVE / "status.csv")


def next_wp_id() -> str:
    used = [int(m.group(1)) for p in OUTBOX.glob("WP-*") if (m := WP_RE.match(p.name))]
    used += [int(m.group(1)) for wp in load_status() if (m := WP_RE.match(wp))]
    return f"WP-{max(used, default=0) + 1:04d}"


def cmd_status(_args) -> int:
    status = load_status()
    if not status:
        print("no packages yet")
    for r in sorted(status.values(), key=lambda r: r["wp_id"]):
        print(f"{r['wp_id']}  {r['state']:10} {r['title'][:50]:50} {r['note']}")
    return 0


# ---------------------------------------------------------------- packages

def known_congregations(state: str, cities: list[str], db: Path, seeds: Path) -> list[dict]:
    """Directory churches around the named cities (bounding box of their pins plus a
    margin, since OSM city labels are often the neighbouring town), plus every Muse
    discovery in those cities."""
    want = {c.lower() for c in cities}
    rows: list[dict] = []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        pins = [(lat, lon) for city, lat, lon in con.execute(
            "select city, latitude, longitude from churches where state = ? and latitude is not null", (state,))
            if (city or "").lower() in want]
        if pins:
            # Trim the outer 2% so a few pins mislabeled with a far-away city name
            # don't stretch the box across the state.
            lats, lons = sorted(p[0] for p in pins), sorted(p[1] for p in pins)
            cut = len(pins) // 50
            lat0, lat1 = lats[cut] - BBOX_MARGIN, lats[-1 - cut] + BBOX_MARGIN
            lon0, lon1 = lons[cut] - BBOX_MARGIN, lons[-1 - cut] + BBOX_MARGIN
            q = ("select church_id, name, city, address, website from churches where state = ? and "
                 "((latitude between ? and ? and longitude between ? and ?) or lower(city) in (%s))"
                 % ",".join("?" * len(want)))
            found = con.execute(q, (state, lat0, lat1, lon0, lon1, *want))
        else:
            found = con.execute("select church_id, name, city, address, website from churches "
                                "where state = ? and lower(city) in (%s)" % ",".join("?" * len(want)),
                                (state, *want))
        for cid, name, city, address, website in found:
            rows.append(dict(known_id=str(cid), kind="directory", name=name or "", current_name="",
                             city=city or "", street_address=address or "", website=website or "",
                             facebook_page_url="", note="directory"))
    finally:
        con.close()
    for r in read_csv(seeds / "muse_candidates.csv"):
        if r["city"].lower() in want:
            rows.append(dict(known_id=r["candidate_id"], kind="candidate", name=r["candidate_name"],
                             current_name=r["current_name_native"], city=r["city"],
                             street_address=r["street_address"], website=r["official_url"],
                             facebook_page_url=r["facebook_page_url"],
                             note=f"found by Muse ({r['task']}); status {r['status']}"))
    rows.sort(key=lambda x: (x["city"], x["name"]))
    return rows


DISCOVERY_TASK = """# {wp_id} — find congregations: {title}

**Rules:** `reference/BRIEF_v3.md` (v3.2) applies in full. How to pick up and deliver: `README_FOR_MUSE.md`.

## What

Find Christian congregations that meet in the cities below and are **not** in `known_congregations.csv`. We care about **coverage**: finding congregations we don't have matters more than filling every fact.

- Report every language the church states (N5).
- De-duplicate by name **and** by address (D4), against `known_congregations.csv` and against your own rows. A known congregation is worth a row only if you add language, service, or children's facts; then set `possible_match_id` to its `known_id`.
- Facts come from the congregation's own site or Page (S1/S2) or its denomination (S3); never from another congregation's site.
- Stay within the caps; report the best-sourced congregations first.

| City | Cap |
|---|---:|
{city_rows}

## Inputs

| File | Rows | sha256 |
|---|---:|---|
| `outbox/{wp_id}/known_congregations.csv` | {known_n} | `{known_sha}` |
| `reference/new_candidates_TEMPLATE_v3.csv` | — | |

## Output (in `returns/{wp_id}/`)

| File | Contents |
|---|---|
| `new_candidates.csv` | `new_candidates_TEMPLATE_v3.csv` columns; `task = {task}`; `candidate_ref` `{task}-001`, `{task}-002`, … |
| `run_log.md` | D9 manifest; sources searched per city; counts per city (found, already known, with kids program, by stated language, Facebook-only); blocked sites; hard rows |
| `DONE.md` | written last; see `README_FOR_MUSE.md` |

## Check before delivering

```bash
python3 reference/validate_returns.py ALL - returns/{wp_id}/new_candidates.csv
```

Zero `ERROR` lines is required. Warnings are fine; explain the unusual ones in `run_log.md`.
"""


def parse_caps(spec: str) -> list[tuple[str, int]]:
    out = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        name, _, cap = part.rpartition("=")
        if not name or not cap.strip().isdigit():
            raise SystemExit(f"bad city spec {part!r}: use 'City=cap'")
        out.append((name.strip(), int(cap)))
    return out


def cmd_new_discovery(args) -> int:
    cities = parse_caps(args.cities)
    other = parse_caps(args.other) if args.other else []
    wp_id = next_wp_id()
    task = wp_id.replace("-", "")
    pkg = OUTBOX / wp_id
    pkg.mkdir(parents=True)
    known = known_congregations(args.state, [c for c, _ in cities], Path(args.db), Path(args.seeds))
    write_csv(pkg / "known_congregations.csv", KNOWN_COLS, known)
    city_rows = "\n".join(f"| {c} | {n} |" for c, n in cities + other)
    (pkg / "TASK.md").write_text(DISCOVERY_TASK.format(
        wp_id=wp_id, task=task, title=args.title, city_rows=city_rows, known_n=len(known),
        known_sha=sha256(pkg / "known_congregations.csv")), encoding="utf-8")
    print(f"{wp_id}: {args.title}; {len(cities) + len(other)} areas, cap {sum(n for _, n in cities + other)}; "
          f"{len(known)} known congregations -> {pkg}")
    print(f"review {pkg / 'TASK.md'}, then: python3 muse_handoff/drive_sync.py publish {wp_id}")
    return 0


LEADS_TASK = """# {wp_id} — check leads: {title}

**Rules:** `reference/BRIEF_v3.md` (v3.2) applies in full. How to pick up and deliver: `README_FOR_MUSE.md`.

## What

`leads.csv` lists {n} congregations from the **IRS list of tax-exempt organizations** that are in neither our directory nor your earlier results. We want to know, for each one, **whether a congregation by that name meets today**, and if so, where. The answer "we can't find it" is just as useful as a find: this package measures how much of the IRS list is real.

The IRS gives a **name, a filing address, and a year**. Treat them as a lead only:
- The IRS address is where the paperwork goes: often a pastor's home, a treasurer, or a mailbox. **Never report it as the church's address** unless the church's own source (S1–S3) states it as the place it meets.
- Don't look up the people who live at an address, and never report a personal name, home, or phone (N1).
- Spend **at most about 5 minutes per lead**: search the name with the city, then the name alone, and check Facebook Pages. If nothing in S1–S4 shows the congregation, the outcome is `no_trace`.

## Output 1: `lead_outcomes.csv`, exactly one row per `lead_id`

| Column | Value |
|---|---|
| `lead_id` | from `leads.csv` |
| `outcome` | `active`: an S1–S3 source, or a Facebook Page post within 12 months, shows it meets now; `closed`: a source says it closed, merged, or dissolved; `no_trace`: nothing found in S1–S4; `not_a_congregation`: a ministry, school, or other organization that holds no regular worship; `out_of_scope`: not a Christian congregation (D-1); `already_known`: it is in `known_congregations.csv` |
| `known_id` | for `already_known`: its `known_id` |
| `evidence_url`, `evidence_type` | the page that decided the outcome (blank for `no_trace`); `own_site` / `fb_page` / `denomination` / `other` |
| `meets_at_irs_address` | `yes` / `no` / `unknown`: does a source say it meets at the IRS street address? |
| `checked_at` | per-row UTC time, `YYYY-MM-DDTHH:MM:SSZ` (D7) |
| `minutes_spent`, `notes` | what you searched, and anything unusual |

## Output 2: `new_candidates.csv`

- For every `active` lead: one full v3 row (`new_candidates_TEMPLATE_v3.csv`) with `candidate_ref` = its `lead_id`, `task = {task}`, and `found_via` as usual.
- For an `already_known` lead: a row only if you add language, service, or children's facts, with `possible_match_id` = the `known_id`.
- Congregations you find along the way that are not leads: `{task}-901`, `{task}-902`, ….

The same source rules apply as always: facts come from the congregation's own site or Page, or its denomination; excerpts are verbatim (N9).

## Inputs

| File | Rows | sha256 |
|---|---:|---|
| `outbox/{wp_id}/leads.csv` | {n} | `{leads_sha}` |
| `outbox/{wp_id}/known_congregations.csv` | {known_n} | `{known_sha}` |

## Output files (in `returns/{wp_id}/`)

`lead_outcomes.csv`, `new_candidates.csv`, `run_log.md` (D9 manifest; counts per outcome; blocked sites), then `DONE.md` last.

## Check before delivering

```bash
python3 reference/validate_returns.py ALL - returns/{wp_id}/new_candidates.csv
```

Zero `ERROR` lines is required. We also check that every lead has exactly one outcome and that every `active` lead has a candidate row.
"""


def cmd_new_leads(args) -> int:
    leads = read_csv(Path(args.leads))
    if not leads:
        raise SystemExit(f"no leads in {args.leads}")
    wp_id = next_wp_id()
    task = wp_id.replace("-", "")
    pkg = OUTBOX / wp_id
    pkg.mkdir(parents=True)
    for i, r in enumerate(leads, 1):
        r["lead_id"] = f"{task}-{i:03d}"
    write_csv(pkg / "leads.csv", LEAD_COLS, leads)
    cities = sorted({r["irs_city"] for r in leads})
    known = known_congregations(args.state, cities, Path(args.db), Path(args.seeds))
    write_csv(pkg / "known_congregations.csv", KNOWN_COLS, known)
    (pkg / "TASK.md").write_text(LEADS_TASK.format(
        wp_id=wp_id, task=task, title=args.title, n=len(leads), leads_sha=sha256(pkg / "leads.csv"),
        known_n=len(known), known_sha=sha256(pkg / "known_congregations.csv")), encoding="utf-8")
    print(f"{wp_id}: {args.title}; {len(leads)} leads in {len(cities)} cities; {len(known)} known -> {pkg}")
    print(f"review {pkg / 'TASK.md'}, then: python3 muse_handoff/drive_sync.py publish {wp_id}")
    return 0


FIX_INPUT_COLS = ["subject_type", "subject_id", "name", "city", "recorded_service_times",
                  "recorded_service_languages", "current_source_url", "reason"]

SERVICE_FIX_TASK = """# {wp_id} — re-quote service times: {title}

**Rules:** `reference/BRIEF_v3.md` (v3.2) applies in full. How to pick up and deliver: `README_FOR_MUSE.md`.

## What

These {n} congregations have a recorded weekend schedule that our map can't show yet, because the excerpt doesn't prove it. `reason` says exactly which times are missing, for example `Sun 10:00 English`. That means the excerpt doesn't state a Sunday 10:00 service in English.

Our rule: a time is shown only if the excerpt states that time **with its day**, for the same kind of gathering, and **in the language the schedule names**.

For each row:
1. **Scope:** keep the weekend worship services (Saturday vigil and Sunday) and every language-specific service. Leave out weekday Masses, classes, and youth nights.
2. **Excerpt:** from the church's own page (or its denomination's), copy a verbatim excerpt of **at most 200 characters** that states each kept time **next to its day and its language**.
   - If the heading and the times are in different places, join the pieces with ` … `, for example `Sunday Masses … 8:00 AM, 10:00 AM … 12:00 PM (Spanish)`.
   - Prefer the passage where each time sits right beside its own label. In lines like `8:00 AM English Mass 9:30 AM Sung Mass`, a label could belong to the time before it or after it, so we can't use them.
3. **Schedule:** `service_times_verbatim` is **only what that excerpt states**, verbatim. If the page states no language for a time, **leave the language out**; don't add one the excerpt doesn't say.
4. **Languages:** `service_languages` as stated (`Mandarin;English`).
5. **No usable text:** if no page states the schedule as text, leave the times blank and say why in `notes`.

## Input

| File | Rows | sha256 |
|---|---:|---|
| `outbox/{wp_id}/service_fix_input.csv` | {n} | `{sha}` |

## Output (in `returns/{wp_id}/`)

- `service_fixes.csv` (`reference/service_fixes_S_TEMPLATE.csv`), exactly one row per input `subject_id`.
- `run_log.md`.
- `DONE.md`, written last.

## Check before delivering

```bash
python3 reference/validate_returns.py --service-fixes returns/{wp_id}/service_fixes.csv
```

Zero `ERROR` lines is required. It applies the same rule as the map.
"""


def current_rows(ids: set[str]) -> list[dict]:
    """The latest returned row (overlays applied) for each id, read the way build_seeds reads it."""
    sys.path.insert(0, str(ROOT / "analytics" / "scripts"))
    import build_seeds as bs  # noqa: PLC0415
    overlays, latest = bs.load_overlays(), {}
    for fname, _ in bs.RESULT_FILES + bs.package_files("results"):
        for r in bs.read(fname) or []:
            if r["church_id"] in ids:
                latest[r["church_id"]] = ("church", bs.apply_overlays(r, "church", r["church_id"], overlays, {}))
    for fname, _ in bs.CANDIDATE_FILES + bs.package_files("new_candidates"):
        for r in bs.read(fname) or []:
            if r.get("candidate_ref") in ids:
                cid = r["candidate_ref"]
                latest[cid] = ("candidate", bs.apply_overlays(r, "candidate", cid, overlays, {}))
    names = {r["church_id"]: r["name"] for r in read_csv(ROOT / "analytics/dbt/seeds/muse_manifest.csv")}
    out = []
    for sid in sorted(ids):
        if sid not in latest:
            raise SystemExit(f"{sid}: no returned row found")
        st, r = latest[sid]
        out.append(dict(subject_type=st, subject_id=sid,
                        name=r.get("current_name") or r.get("candidate_name") or names.get(sid, ""),
                        city=r.get("city", ""), recorded_service_times=r.get("service_times_verbatim", ""),
                        recorded_service_languages=r.get("service_languages", ""),
                        current_source_url=r.get("service_source_url", ""),
                        reason=_reason(r.get("service_excerpt", ""), r.get("service_times_verbatim", ""))))
    return out


def _reason(excerpt: str, verbatim: str) -> str:
    from validate_returns import TIME_RE, unsupported_slots  # noqa: PLC0415
    if not TIME_RE.search(excerpt or ""):
        return "excerpt has no time"
    missing = unsupported_slots(excerpt, verbatim)
    return "excerpt does not state: " + "; ".join(missing) if missing else "excerpt supports it (re-check the page)"


def cmd_new_service_fixes(args) -> int:
    ids = {x.strip() for x in args.ids.split(",") if x.strip()}
    rows = current_rows(ids)
    wp_id = next_wp_id()
    pkg = OUTBOX / wp_id
    pkg.mkdir(parents=True)
    write_csv(pkg / "service_fix_input.csv", FIX_INPUT_COLS, rows)
    (pkg / "TASK.md").write_text(SERVICE_FIX_TASK.format(
        wp_id=wp_id, title=args.title, n=len(rows), sha=sha256(pkg / "service_fix_input.csv")), encoding="utf-8")
    print(f"{wp_id}: {args.title}; {len(rows)} rows -> {pkg}")
    print(f"review {pkg / 'TASK.md'}, then: python3 muse_handoff/drive_sync.py publish {wp_id}")
    return 0


def check_leads(wp_id: str, outcomes: Path, cands: Path | None) -> list[str]:
    """Every lead exactly once with a known outcome; every active lead has a candidate row."""
    leads = {r["lead_id"] for r in read_csv(OUTBOX / wp_id / "leads.csv")}
    rows = read_csv(outcomes)
    errs = []
    if rows and set(OUTCOME_COLS) - set(rows[0]):
        errs.append(f"ERROR lead_outcomes.csv is missing columns: {sorted(set(OUTCOME_COLS) - set(rows[0]))}")
    seen = Counter(r.get("lead_id", "") for r in rows)
    errs += [f"ERROR {lid}: {n} outcome rows (want exactly 1)" for lid, n in sorted(seen.items()) if n > 1]
    errs += [f"ERROR {lid}: no outcome row" for lid in sorted(leads - set(seen))]
    errs += [f"ERROR {lid}: not a lead in leads.csv" for lid in sorted(set(seen) - leads)]
    refs = {r["candidate_ref"] for r in read_csv(cands)} if cands else set()
    for r in rows:
        lid, outcome = r.get("lead_id", ""), r.get("outcome", "")
        if outcome not in LEAD_OUTCOMES:
            errs.append(f"ERROR {lid}: outcome={outcome!r} not allowed")
        if outcome == "active" and lid not in refs:
            errs.append(f"ERROR {lid}: outcome active but no new_candidates row with candidate_ref {lid}")
        if outcome == "already_known" and not r.get("known_id"):
            errs.append(f"ERROR {lid}: outcome already_known needs known_id")
        if outcome in ("active", "closed", "not_a_congregation", "out_of_scope") and not r.get("evidence_url"):
            errs.append(f"ERROR {lid}: outcome {outcome} needs evidence_url")
    return errs


def sync_reference() -> None:
    copy_if_changed(HANDOFF / "drive" / "README_FOR_MUSE.md", DRIVE / "README_FOR_MUSE.md")
    for name in REFERENCE:
        copy_if_changed(HANDOFF / name, DRIVE / "reference" / name)


def cmd_publish(args) -> int:
    wp_id = args.wp_id
    src, dst = OUTBOX / wp_id, DRIVE / "outbox" / wp_id
    if not WP_RE.match(wp_id) or not (src / "TASK.md").exists():
        raise SystemExit(f"{src}/TASK.md not found")
    if not DRIVE.exists():
        raise SystemExit(f"Drive folder {DRIVE} not mounted")
    if dst.exists():
        raise SystemExit(f"{dst} already exists; Muse may have started it. Publish a new package instead.")
    status = load_status()
    if wp_id in status:
        raise SystemExit(f"{wp_id} is already in status.csv ({status[wp_id]['state']})")
    sync_reference()
    for f in sorted(src.iterdir()):
        if f.is_file():
            copy_if_changed(f, dst / f.name)
    title = (src / "TASK.md").read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
    status[wp_id] = dict(wp_id=wp_id, title=title, state="queued", published_at=now_utc())
    save_status(status)
    print(f"published {wp_id} to {dst}")
    return 0


# ---------------------------------------------------------------- pull

def parse_done(text: str) -> tuple[dict[str, str], bool]:
    """{file name: sha256} for every listed file, and whether the delivery is partial."""
    files = {}
    for line in text.splitlines():
        m = SHA_RE.search(line)
        if not m:
            continue
        for name in list(OUTPUT_KINDS) + ["run_log.md"]:
            if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", line):
                files[name] = m.group(1)
    partial = bool(re.search(r"^\s*partial\s*:\s*yes\b", text, re.I | re.M))
    return files, partial


def validate(kind: str, path: Path, received: str, wp_id: str) -> tuple[bool, str]:
    """wp_id is the package folder name (WP-0001), which is where its manifest lives."""
    validator = HANDOFF / "validate_returns.py"
    if kind == "new_candidates":
        argv = ["ALL", "-", str(path)]
    elif kind == "results":
        manifest = OUTBOX / wp_id / "manifest.csv"
        if not manifest.exists():
            return False, f"ERROR results.csv returned but {wp_id} has no manifest; this package expects no results.csv\n"
        argv = ["ALL", str(path), "-", "--redo", "--manifest", str(manifest)]
    elif kind == "service_fixes":
        argv = ["--service-fixes", str(path)]
    else:
        return True, ""  # W answers are gated by recheck and build_seeds; lead outcomes by check_leads
    p = subprocess.run([sys.executable, "-I", str(validator), *argv, "--received-at", received],
                       capture_output=True, text=True)
    return p.returncode == 0, p.stdout + p.stderr


def write_feedback(wp_id: str, problems: list[str]) -> None:
    body = (f"# Feedback on {wp_id} ({now_utc()})\n\n"
            "We did not ingest this delivery. Please fix the files in "
            f"`returns/{wp_id}/` in place and then rewrite `DONE.md` with the new hashes. "
            "Never edit an excerpt to pass a check (N9): copy a new verbatim excerpt or blank the fact.\n\n")
    body += "\n".join(problems) + "\n"
    out = DRIVE / "feedback" / f"{wp_id}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")


def record_received(entries: list[dict]) -> None:
    rows = {r["file"]: r for r in read_csv(RET / "received.csv")}
    rows.update({e["file"]: e for e in entries})
    write_csv(RET / "received.csv", RECEIVED_COLS, sorted(rows.values(), key=lambda r: r["file"]))


def pull_package(wp_dir: Path, status: dict[str, dict], recheck: bool) -> str:
    """Process one returns/WP-xxxx/ folder. Returns what happened."""
    wp_id = wp_dir.name
    row = status.get(wp_id)
    if row is None:
        return "unknown package (not in status.csv); left alone"
    if row["state"] == "queued" and (wp_dir / "STARTED.md").exists():
        row.update(state="started", started_at=mtime_utc(wp_dir / "STARTED.md"))
    done = wp_dir / "DONE.md"
    if not done.exists():
        return row["state"]
    done_sha = sha256(done)
    if row.get("done_sha256") == done_sha:
        return f"{row['state']} (no new DONE.md)"
    listed, partial = parse_done(done.read_text(encoding="utf-8", errors="replace"))
    outputs = {n: s for n, s in listed.items() if n in OUTPUT_KINDS}
    if not outputs:
        row.update(state="needs_fix", done_sha256=done_sha, note="DONE.md lists no output file with its sha256")
        write_feedback(wp_id, [f"- `DONE.md` must list each output file with its sha256 (see README_FOR_MUSE.md)."])
        return row["state"]
    for name, want in listed.items():
        f = wp_dir / name
        if not f.exists() or sha256(f) != want:
            return f"waiting: {name} missing or its sha256 differs from DONE.md (Drive may still be syncing)"
    received = mtime_utc(done)
    row.update(state="delivered", delivered_at=received)
    stage = RET / "staging" / wp_id
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    problems, staged, notes = [], [], []
    tag = wp_id.replace("-", "")
    for name in sorted(outputs):
        kind = OUTPUT_KINDS[name]
        local = stage / f"{kind}_{tag}.csv"
        shutil.copyfile(wp_dir / name, local)
        ok, out = validate(kind, local, received, wp_id)
        errors = [ln for ln in out.splitlines() if ln.startswith("ERROR")]
        # A stamp later than the delivery is not a real check time. build_seeds marks it
        # unreliable and blanks it, and the recheck verifies the excerpt itself, so it
        # doesn't block the facts (same handling as batch A's reconstructed stamps).
        late = [ln for ln in errors if LATE_STAMP in ln]
        if late:
            notes.append(f"{len(late)} checked_at stamp(s) after delivery in {name}; marked unreliable")
        blocking = [ln for ln in errors if LATE_STAMP not in ln]
        if not ok and (blocking or not errors):
            problems.append(f"## `{name}`\n\n```\n" + "\n".join(blocking or out.splitlines()[-20:]) + "\n```\n")
        staged.append(local)
    # What the package asked for decides which answers must come back, not what the
    # return happens to list: leaving lead_outcomes.csv out must not skip its check.
    fix_input = OUTBOX / wp_id / "service_fix_input.csv"
    if fix_input.exists() and "service_fixes.csv" not in outputs:
        problems.append("## `service_fixes.csv`\n\nMissing: this package asks for one row per input subject.\n")
    elif fix_input.exists():
        want = {(r["subject_type"], r["subject_id"]) for r in read_csv(fix_input)}
        got = {(r.get("subject_type", ""), r.get("subject_id", "")) for r in read_csv(stage / f"service_fixes_{tag}.csv")}
        errs = [f"ERROR {t}:{i}: no row in service_fixes.csv" for t, i in sorted(want - got)]
        errs += [f"ERROR {t}:{i}: not in service_fix_input.csv" for t, i in sorted(got - want)]
        if errs:
            problems.append("## `service_fixes.csv`\n\n```\n" + "\n".join(errs) + "\n```\n")
    if (OUTBOX / wp_id / "leads.csv").exists() and "lead_outcomes.csv" not in outputs:
        problems.append("## `lead_outcomes.csv`\n\nMissing: this package asks for one outcome per `lead_id`.\n")
    elif (OUTBOX / wp_id / "leads.csv").exists():
        cands = stage / f"new_candidates_{tag}.csv"
        errs = check_leads(wp_id, stage / f"lead_outcomes_{tag}.csv", cands if cands.exists() else None)
        if errs:
            problems.append("## `lead_outcomes.csv`\n\n```\n" + "\n".join(errs) + "\n```\n")
    if problems:
        row.update(state="needs_fix", done_sha256=done_sha, note=f"{len(problems)} file(s) failed validation")
        write_feedback(wp_id, problems)
        return row["state"]
    for local in staged:
        shutil.copyfile(local, RET / local.name)
    if (wp_dir / "run_log.md").exists():
        shutil.copyfile(wp_dir / "run_log.md", RET / f"run_log_{tag}.md")
    record_received([dict(file=p.name, wp_id=wp_id, received_at=received, done_sha256=done_sha) for p in staged])
    shutil.rmtree(stage, ignore_errors=True)
    cited = [str(RET / p.name) for p in staged if p.name.rsplit("_", 1)[0] in RECHECKED]
    if recheck and cited:  # lead_outcomes.csv alone (say, every lead no_trace) cites nothing to re-check
        p = subprocess.run([str(ROOT / "analytics/.venv/bin/python"), str(ROOT / "analytics/scripts/recheck_sources.py"),
                            *cited])
        if p.returncode != 0:  # DONE.md not recorded as handled, so the next pull retries
            return "waiting: source re-check failed; will retry"
    if partial:
        notes.append("partial delivery; queue the rest")
    # Accepted, but "ingested" only once seeds and dbt have been rebuilt with it (cmd_pull).
    row.update(state="pending_build", done_sha256=done_sha, note="; ".join(notes))
    fb = DRIVE / "feedback" / f"{wp_id}.md"
    if fb.exists():
        fb.unlink()  # ours to remove: the problems it listed are fixed
    return row["state"]


def rebuild() -> str:
    """Rebuild seeds and dbt. Returns "" on success, else what failed."""
    if subprocess.run([sys.executable, str(ROOT / "analytics/scripts/build_seeds.py")]).returncode != 0:
        return "build_seeds.py failed"
    env = {**os.environ, "DBT_PROFILES_DIR": str(ROOT / "analytics/dbt")}
    p = subprocess.run([str(ROOT / "analytics/.venv/bin/dbt"), "build", "--project-dir", str(ROOT / "analytics/dbt"),
                        "--full-refresh", "--quiet"], env=env)
    return "" if p.returncode == 0 else "dbt build failed"


def cmd_pull(args) -> int:
    if not DRIVE.exists():
        raise SystemExit(f"Drive folder {DRIVE} not mounted")
    sync_reference()  # README/brief changes reach Muse without a new package
    status = load_status()
    for wp in args.again:  # forget the handled DONE.md so the same delivery is processed again
        if wp in status:
            status[wp]["done_sha256"] = ""
    for wp_dir in sorted((DRIVE / "returns").glob("WP-*")):
        if not (wp_dir.is_dir() and WP_RE.match(wp_dir.name)):
            continue
        print(f"{wp_dir.name}: {pull_package(wp_dir, status, recheck=not args.no_recheck)}")
    save_status(status)
    # Every accepted package not yet built in, including ones whose build failed before:
    # their DONE.md is already handled, so this is the only place they get retried.
    pending = sorted(wp for wp, r in status.items() if r["state"] in ("pending_build", "build_failed"))
    rc = 0
    if pending and not args.no_build:
        failed = rebuild()
        for wp in pending:
            if failed:
                status[wp].update(state="build_failed", build_error=f"{failed} at {now_utc()}; retried on the next pull")
            else:
                status[wp].update(state="ingested", ingested_at=now_utc(), build_error="")
        save_status(status)
        print(f"rebuild {'FAILED: ' + failed if failed else 'ok'} for {', '.join(pending)}")
        rc = 1 if failed else 0
    queued = sum(r["state"] in ("queued", "needs_fix") for r in status.values())
    print(f"{queued} package(s) waiting for Muse")
    if queued == 0:
        print("queue is empty: make the next package with new-discovery, then publish it")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("new-discovery", help="build a discovery package in muse_handoff/outbox/")
    p.add_argument("--title", required=True)
    p.add_argument("--state", required=True, help="two-letter state code")
    p.add_argument("--cities", required=True, help="'City=cap,City=cap'")
    p.add_argument("--other", default="", help="extra rows without a known list, e.g. 'Any other Marin city=10'")
    p.add_argument("--db", default=str(ROOT / "holyhub.db"), help="local directory snapshot (read only)")
    p.add_argument("--seeds", default=str(ROOT / "analytics/dbt/seeds"))
    p.set_defaults(fn=cmd_new_discovery)
    p = sub.add_parser("new-leads", help="build a lead-checking package from a leads CSV (irs_leads.py)")
    p.add_argument("--title", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--leads", required=True)
    p.add_argument("--db", default=str(ROOT / "holyhub.db"))
    p.add_argument("--seeds", default=str(ROOT / "analytics/dbt/seeds"))
    p.set_defaults(fn=cmd_new_leads)
    p = sub.add_parser("new-service-fixes", help="ask Muse to re-quote service times for these subjects")
    p.add_argument("--title", required=True)
    p.add_argument("--ids", required=True, help="comma-separated church_ids and candidate refs")
    p.set_defaults(fn=cmd_new_service_fixes)
    p = sub.add_parser("publish", help="copy a package to the Drive outbox and queue it")
    p.add_argument("wp_id")
    p.set_defaults(fn=cmd_publish)
    p = sub.add_parser("pull", help="ingest delivered packages")
    p.add_argument("--no-recheck", action="store_true")
    p.add_argument("--no-build", action="store_true")
    p.add_argument("--again", nargs="*", default=[], metavar="WP-xxxx",
                   help="process these packages' current DONE.md again (after a rule change)")
    p.set_defaults(fn=cmd_pull)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
