"""Build dbt seeds from the gitignored Muse returns.

Reads muse_handoff/returns/ (raw returns contain verbatim website and Facebook
excerpts and stay out of git) and writes sanitized seeds to analytics/dbt/seeds/.
Muse-derived seeds are gitignored too, because this repo is public and Muse's
output-reuse terms are open (plan §12).

  muse_manifest.csv     every OSM manifest sent to Muse (public OSM data)
  muse_results.csv      one current verdict per manifest church across all passes;
                        no excerpts or notes; D-2 personal phones removed
  muse_candidates.csv   congregations Muse found outside the directory, v2 (A, B)
                        and v3 (CN, C, D, E, F, L) unified; task E's full v3 rows
                        replace the A/B rows they rebuild
  source_checks.csv     re-verification verdict per (subject, fact group), taken
                        from returns/recheck/<file that produced the row>.csv; a verdict
                        whose fact fingerprint no longer matches the row is "stale"
  quality_reviews.csv   the owner's blind audit, scored against Muse's answers
  dedup_candidates.csv  May dedup report (OSM duplicate pairs)
  geocodes.csv          Census pins from analytics/exports/geocode_output.csv, each with
                        the address it was geocoded from (the input whose sha256 the
                        run recorded), so dbt can tell when the record has moved on

Static seeds (denomination_scope.csv, fact_holds.csv) are hand-maintained.

    python3 analytics/scripts/build_seeds.py [--returns DIR]

Returns that have not arrived yet are skipped, so the build works at every
stage. A returned file without a re-check is reported: its web facts stay
hidden until recheck_sources.py has run on it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "analytics" / "dbt" / "seeds"
HANDOFF = ROOT / "muse_handoff"
EXPORTS = ROOT / "analytics" / "exports"  # geocoding files (gitignored)

sys.path.insert(0, str(HANDOFF))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fact_fingerprint import FACT_FIELDS, fact_fingerprint  # noqa: E402
from validate_returns import NEGATED_PERSONAL_RE, PERSONAL_PHONE_RE, STRICT_TS_RE  # noqa: E402
from validate_returns import excerpt_supports_service, excerpt_supports_street  # noqa: E402
from validate_returns import TIME_RE as EXCERPT_TIME_RE  # noqa: E402  (grading has its own TIME_RE)

RET = HANDOFF / "returns"  # replaced by --returns

# checked_at values the batch A run log admits were reconstructed after the fact.
UNRELIABLE_STAMPS = {"2026-10-19T17:40:00Z", "2026-10-19T16:55:00Z",
                     "2026-10-19T16:51:38Z", "2026-10-19T16:48:35Z"}

# When each return reached us (UTC). A checked_at that is malformed or later than
# this cannot be a real check time (seen in batch A and task D).
RECEIVED_AT = {
    "results_A.csv": "2026-10-19T17:27:00Z", "new_candidates_A.csv": "2026-10-19T17:27:00Z",
    "results_B.csv": "2026-10-19T18:13:07Z", "new_candidates_B.csv": "2026-10-19T18:13:07Z",
    "results_FB.csv": "2026-10-19T19:53:34Z", "new_candidates_CN.csv": "2026-10-20T17:31:34Z",
    "results_E.csv": "2026-10-20T17:31:34Z", "new_candidates_E.csv": "2026-10-20T17:31:34Z",
    "results_D.csv": "2026-10-20T20:20:41Z", "new_candidates_D.csv": "2026-10-20T20:20:41Z",  # fill pass
    "results_C.csv": "2026-10-20T19:56:50Z", "new_candidates_C.csv": "2026-10-20T19:56:50Z",
    "results_F.csv": "2026-10-20T23:34:24Z",
    "new_candidates_F.csv": "2026-10-21T17:46:01Z", "new_candidates_L.csv": "2026-10-21T17:46:37Z",
    # round 6, read from the shared Drive folder (file times there)
    "service_fixes_S.csv": "2026-10-21T18:40:02Z", "worship_location_W.csv": "2026-10-21T18:40:12Z",
    "results_H.csv": "2026-10-21T18:48:32Z", "new_candidates_H.csv": "2026-10-21T18:48:33Z",
}

# Work packages delivered through the shared Drive folder (muse_handoff/drive_sync.py)
# land as <kind>_WP0001.csv; their receive times are in returns/received.csv.
PACKAGE_RE = re.compile(r"^(results|new_candidates|service_fixes|worship_location)_(WP\d{4})\.csv$")


def package_files(kind: str) -> list[tuple[str, str]]:
    """[(file name, package id)] for one kind, in package order (a later package wins)."""
    out = []
    for p in sorted(RET.glob(f"{kind}_WP*.csv")):
        m = PACKAGE_RE.match(p.name)
        if m and m.group(1) == kind:
            out.append((p.name, m.group(2)))
    return out


def received_at(fname: str) -> str:
    if fname in RECEIVED_AT:
        return RECEIVED_AT[fname]
    path = RET / "received.csv"
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["file"] == fname:
                    return r["received_at"]
    return ""


MANIFESTS = [  # (file, batch for rows whose manifest has no batch column)
    ("peninsula_seed_v1.csv", None),
    ("batch_C_manifest.csv", "C_main"),
    ("batch_D_manifest.csv", "D_main"),
    ("batch_F_manifest.csv", "F_main"),
]
MANIFEST_COLS = ["church_id", "name", "known_city", "state", "latitude", "longitude", "known_street",
                 "known_website", "known_phone", "osm_ref", "denomination_hint", "gaps", "handling", "batch"]

# Result files in override order: a later file wins for the same church_id.
RESULT_FILES = [("results_current.csv", None), ("results_E.csv", "E"),
                ("results_C.csv", "C"), ("results_D.csv", "D"), ("results_F.csv", "F"), ("results_H.csv", "H")]
GROUPS = ("status", "address", "phone", "service", "kids")
RESULT_COLS = [
    "church_id", "batch", "entity_type", "status", "status_source_url", "status_source_type",
    "current_name", "official_url", "url_evidence", "facebook_page_url", "fb_page_evidence",
    "fb_last_post_date", "street_address", "city", "state", "zip", "address_source_url",
    "address_source_type", "address_is_worship_location", "meets_in_building_of", "pin_check",
    "phone", "phone_source_url", "phone_source_type", "service_times_verbatim",
    "service_languages", "service_source_url", "service_source_type", "kids_program_verbatim",
    "kids_source_url", "kids_source_type", "match_confidence", "duplicate_of_church_id",
    "checked_at", "personal_phone_withheld", "checked_at_reliable", "service_times_unsupported",
    "address_unsupported", "last_pass", "source_file",
]

# Candidate files in override order; task E rebuilds A/B rows under the same ref.
CANDIDATE_FILES = [("new_candidates_A.csv", "A"), ("new_candidates_B.csv", "B"),
                   ("new_candidates_CN.csv", "CN"), ("new_candidates_C.csv", "C"),
                   ("new_candidates_D.csv", "D"), ("new_candidates_E.csv", "E"),
                   ("new_candidates_F.csv", "F"), ("new_candidates_L.csv", "L"),
                   ("new_candidates_H.csv", "H")]

# Overlay files: answers to targeted follow-up tasks, applied on top of the latest row
# for the same subject before fingerprinting and sanitizing, so every gate applies.
OVERLAY_S = "service_fixes_S.csv"      # task S: service times re-quoted from the page
OVERLAY_W = "worship_location_W.csv"   # task W: is this where they meet / corrected street
STALE_W: set[tuple[str, str]] = set()  # W answers dropped because the address they answered changed
SERVICE_COLS = ("service_times_verbatim", "service_languages", "service_source_url", "service_source_type",
                "service_excerpt")
CAND_COLS = [
    "candidate_id", "task", "format", "candidate_name", "current_name_native", "denomination_stated",
    "city", "state", "zip", "official_url", "url_evidence", "facebook_page_url", "fb_page_evidence",
    "fb_last_post_date", "status", "status_source_url", "status_source_type", "street_address",
    "address_source_url", "address_source_type", "address_is_worship_location", "host_church_id",
    "host_venue_name", "phone", "phone_source_url", "phone_source_type", "service_times_verbatim",
    "service_languages", "service_source_url", "service_source_type", "kids_program_verbatim",
    "kids_source_url", "kids_source_type", "possible_match_church_id", "possible_match_candidate_id",
    "duplicate_of_church_id", "match_confidence", "found_via", "checked_at", "checked_at_reliable",
    "personal_phone_withheld", "service_times_unsupported", "address_unsupported", "last_pass", "source_file",
]

# Duplicates we established that Muse did not mark (plan §6: B outcome, CN outcome).
# C-030 and C-064: same name, address and website as a directory church; found when
# their Census pins landed on that church's pin (dbt assert_new_congregations_are_not_in_the_directory).
CANDIDATE_DUPLICATES = {"CN-025": "78022", "C-030": "76688", "C-064": "77437"}
CANDIDATE_DUPLICATES_BY_NAME = {("B", "Bridge City Church"): "76692"}

LANGUAGE_NAMES = {
    "mandarin": "Mandarin", "國語": "Mandarin", "国语": "Mandarin", "普通話": "Mandarin", "普通话": "Mandarin",
    "cantonese": "Cantonese", "粵語": "Cantonese", "粤语": "Cantonese", "廣東話": "Cantonese",
    "taiwanese": "Taiwanese", "台語": "Taiwanese", "台语": "Taiwanese", "chinese": "Chinese", "中文": "Chinese",
    "english": "English", "spanish": "Spanish", "español": "Spanish", "korean": "Korean",
    "vietnamese": "Vietnamese", "tagalog": "Tagalog", "filipino": "Tagalog", "japanese": "Japanese",
}


# ---------------------------------------------------------------- helpers

def read(name: str) -> list[dict] | None:
    path = RET / name
    if not path.exists():
        return None
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write(name: str, cols: list[str], rows: list[dict]) -> None:
    with (SEEDS / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


def normalize_languages(value: str) -> str:
    out = []
    for part in re.split(r"[;,/、]|\band\b", value or ""):
        p = part.strip()
        if not p:
            continue
        name = LANGUAGE_NAMES.get(p.lower(), p[:1].upper() + p[1:])
        if name not in out:
            out.append(name)
    return ";".join(out)


BULK_STAMP_ROWS = 10  # more rows than this sharing one checked_at = stamped at write time, not per check


def bulk_stamps(rows: list[dict]) -> set[str]:
    counts: dict[str, int] = {}
    for r in rows:
        if r.get("checked_at"):
            counts[r["checked_at"]] = counts.get(r["checked_at"], 0) + 1
    return {ts for ts, n in counts.items() if n > BULK_STAMP_ROWS}


def sanitize(r: dict, fname: str = "", bulk: frozenset = frozenset()) -> dict:
    """D-2 personal phones, unreliable timestamps, unsupported times, language format."""
    ctx = NEGATED_PERSONAL_RE.sub("", r.get("notes", "") + " " + r.get("phone_excerpt", ""))
    personal = bool(r.get("phone")) and bool(PERSONAL_PHONE_RE.search(ctx))
    if personal or "personal number withheld" in r.get("notes", "").lower():
        r.update(phone="", phone_source_url="", phone_source_type="")
        r["personal_phone_withheld"] = "true"
    else:
        r["personal_phone_withheld"] = "false"
    ts, received = r.get("checked_at", ""), received_at(fname)
    reliable = (ts not in UNRELIABLE_STAMPS and ts not in bulk
                and (not ts or STRICT_TS_RE.match(ts) is not None)
                and not (received and ts > received))
    r["checked_at_reliable"] = "true" if reliable else "false"
    if not reliable:
        r["checked_at"] = ""
    # The service group has one excerpt for times and languages. If it backs only the
    # languages (no time in it), the times are unsupported and are not published.
    if r.get("service_times_verbatim") and r.get("service_excerpt") and (
            not EXCERPT_TIME_RE.search(r["service_excerpt"])
            or not excerpt_supports_service(r["service_excerpt"], r["service_times_verbatim"])):
        # The excerpt has no time, or not the same times on the same days.
        r["service_times_verbatim"] = ""
        r["service_times_unsupported"] = "true"
    else:
        r["service_times_unsupported"] = "false"
    # An address is published only if its excerpt states that exact street address
    # (house number + every street word). "107 San Mateo Avenue" is not evidence for
    # "107 San Pedro Road", even when the passage is really on the cited page.
    addr_ex = r.get("address_excerpt") if "address_excerpt" in r else r.get("excerpt", "")
    if r.get("street_address") and not excerpt_supports_street(addr_ex or "", r["street_address"]):
        r["street_address"] = ""
        r["address_unsupported"] = "true"
    else:
        r["address_unsupported"] = "false"
    wl = (r.get("address_is_worship_location") or "").strip().lower()
    r["address_is_worship_location"] = {"true": "yes", "false": "no"}.get(wl, wl)  # agent wrote True/False
    r["service_languages"] = normalize_languages(r.get("service_languages", ""))
    return r


def pilot_pass_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for name, label in (("results_A.csv", "A"), ("results_B.csv", "B"), ("results_A_redo.csv", "A_redo")):
        m.update({r["church_id"]: label for r in read(name) or []})
    # Rows taken from the logged-in Facebook check when building results_A_v3.
    m.update({cid: "A_fbcheck" for cid in ("76673", "76674", "76677", "76678", "76683", "77956")})
    m.update({r["church_id"]: "FB1" for r in read("results_FB.csv") or []})
    return m


# ---------------------------------------------------------------- builders

def build_manifest() -> dict[str, str]:
    rows, batch_of = [], {}
    # A verification work package carries its own manifest: outbox/WP-0001/manifest.csv.
    packages = [(str(p.relative_to(HANDOFF)), p.parent.name.replace("-", ""))
                for p in sorted((HANDOFF / "outbox").glob("WP-[0-9][0-9][0-9][0-9]/manifest.csv"))]
    for fname, batch in MANIFESTS + packages:
        path = HANDOFF / fname
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["batch"] = r.get("batch") or batch
                r["handling"] = r.get("handling") or "full"
                batch_of[r["church_id"]] = r["batch"]
                rows.append(r)
    write("muse_manifest.csv", MANIFEST_COLS, rows)
    return batch_of


def w_input_path(fname: str) -> Path:
    """The input a W answer file was asked from: round 6's, or its package's."""
    m = PACKAGE_RE.match(fname)
    if m:
        return HANDOFF / "outbox" / f"WP-{m.group(2)[2:]}" / "worship_location_input.csv"
    return HANDOFF / "outbox" / "worship_location_W_input.csv"


def asked_address(r: dict) -> str:
    """The recorded address a W question was about (street + city, case and spacing ignored)."""
    return "|".join(" ".join((r.get(f) or "").split()).casefold() for f in ("street_address", "city"))


def load_overlays() -> tuple[dict, dict]:
    """(S rows, W rows) keyed by (subject_type, subject_id). A W answer is used only if
    its own excerpt re-verified on its page with the same fingerprint; otherwise the
    record keeps what it had (an unproven "yes" must not make an address visit-ready).
    It is also bound to the address it was asked about (`_asked`); an answer whose
    question we can't find is not used."""
    s_rows, w_rows = {}, {}
    for fname in [OVERLAY_S] + [f for f, _ in package_files("service_fixes")]:
        for r in read(fname) or []:
            s_rows[(r["subject_type"], r["subject_id"])] = {**r, "_file": fname}
    for fname in [OVERLAY_W] + [f for f, _ in package_files("worship_location")]:
        checks_path = RET / "recheck" / f"{Path(fname).stem}.csv"
        checks = {}
        if checks_path.exists():
            with checks_path.open(encoding="utf-8") as f:
                checks = {r["row_key"]: r for r in csv.DictReader(f) if r["group"] == "worship"}
        asked = {}
        if w_input_path(fname).exists():
            with w_input_path(fname).open(encoding="utf-8") as f:
                asked = {(r["subject_type"], r["subject_id"]): asked_address(r) for r in csv.DictReader(f)}
        for r in read(fname) or []:
            key = (r["subject_type"], r["subject_id"])
            c = checks.get(r["subject_id"])
            if key in asked and c and c["verdict"] == "verified" and \
                    c.get("fact_fingerprint") == fact_fingerprint(r, "worship"):
                w_rows[key] = {**r, "_file": fname, "_asked": asked[key]}
    return s_rows, w_rows


def release(used: dict, subject_type: str, sid: str) -> None:
    """A newer record for this subject replaces the older one: whatever S/W owned for
    the older record is decided again for the newer one."""
    for group in ("service", "address"):
        used.pop((subject_type, sid, group), None)


def apply_overlays(raw: dict, subject_type: str, sid: str, overlays: tuple[dict, dict],
                   used: dict) -> dict:
    """Merge S/W answers into a raw returned row; record which fact groups they now own.
    Called for every pass in order, so ownership always describes the latest record."""
    s_rows, w_rows = overlays
    raw = dict(raw)
    release(used, subject_type, sid)
    o = s_rows.get((subject_type, sid))
    if o:
        for c in SERVICE_COLS:
            raw[c] = o.get(c, "")  # S is newer and stricter; a blank answer clears the old schedule
        used[(subject_type, sid, "service")] = (o["_file"], "service", o)
    o = w_rows.get((subject_type, sid))
    if o and o["_asked"] != asked_address(raw):
        # The record's address changed after W was asked: the answer is about another
        # address (a "yes" for 100 Main St says nothing about 200 Main St). Ask again.
        STALE_W.add((subject_type, sid))
        o = None
    if o:
        ans = (o.get("address_is_worship_location") or "").strip().lower()
        if o.get("worship_street_address") and ans == "no":
            # "no" answers for the recorded address; the worship address W gives in its
            # place is, by the task's definition, where they meet.
            ans = "yes"
        if ans in ("yes", "no", "unknown"):
            raw["address_is_worship_location"] = ans
        if o.get("worship_street_address"):
            raw.update(street_address=o["worship_street_address"], city=o.get("worship_city") or raw.get("city", ""),
                       zip=o.get("worship_zip") or raw.get("zip", ""), address_source_url=o.get("source_url", ""),
                       address_source_type=o.get("source_type", ""), address_excerpt=o.get("excerpt", ""))
            used[(subject_type, sid, "address")] = (o["_file"], "worship", o)
    return raw


def raw_fingerprints(raw: dict, groups) -> dict[str, str]:
    """Fingerprints of the facts in a raw returned row (before sanitizing)."""
    return {g: fact_fingerprint(raw, g) for g in groups}


def build_results(batch_of: dict[str, str], overlays: tuple[dict, dict] = ({}, {}), used: dict | None = None
                  ) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Returns ({church_id: source file}, {(church_id, group): fact fingerprint})."""
    used = {} if used is None else used
    pilot_passes = pilot_pass_map()
    current: dict[str, dict] = {}
    fps: dict[tuple[str, str], str] = {}
    for fname, label in RESULT_FILES + package_files("results"):
        rows = read(fname)
        if rows is None:
            continue
        bulk = frozenset(bulk_stamps(rows))
        for raw in rows:
            raw = apply_overlays(raw, "church", raw["church_id"], overlays, used)
            for g, fp in raw_fingerprints(raw, GROUPS).items():
                fps[(raw["church_id"], g)] = fp
            r = sanitize(dict(raw), fname, bulk)
            r["last_pass"] = label or pilot_passes.get(r["church_id"], "A")
            r["source_file"] = fname
            r["batch"] = batch_of.get(r["church_id"], "")
            current[r["church_id"]] = r
    out = sorted(current.values(), key=lambda r: int(r["church_id"]))
    write("muse_results.csv", RESULT_COLS, out)
    return {r["church_id"]: r["source_file"] for r in out}, fps


def candidate_from_v2(r: dict, cid: str, task: str) -> dict:
    """A/B rows carry one source for the whole row; it backs the address if there is one."""
    has_addr = bool(r.get("street_address"))
    return {
        **r, "candidate_id": cid, "task": task, "format": "v2", "status": "",
        "address_source_url": r.get("source_url", "") if has_addr else "",
        "address_source_type": r.get("source_type", "") if has_addr else "",
        "possible_match_id": r.get("possible_match_church_id", ""),
    }


def build_candidates(overlays: tuple[dict, dict] = ({}, {}), used: dict | None = None
                     ) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    used = {} if used is None else used
    current: dict[str, dict] = {}
    fps: dict[tuple[str, str], str] = {}
    for fname, task in CANDIDATE_FILES + package_files("new_candidates"):
        rows = read(fname)
        if rows is None:
            continue
        bulk = frozenset(bulk_stamps(rows))
        for i, r in enumerate(rows, 1):
            if "candidate_ref" in r:  # v3
                cid = r["candidate_ref"]
                r = apply_overlays(r, "candidate", cid, overlays, used)
                for g, fp in raw_fingerprints(r, GROUPS).items():
                    fps[(cid, g)] = fp
                r = {**r, "candidate_id": cid, "task": r.get("task") or task, "format": "v3"}
                # A work package that re-delivers a ref is a re-check (refs are permanent, D11):
                # the region/round the candidate came from stays. Task E's rebuild of A/B is a pass of its own.
                if cid in current and re.match(r"WP\d{4}$", task):
                    r["task"] = current[cid]["task"]
            else:
                cid = f"{task}-{i:02d}"
                release(used, "candidate", cid)
                for g in GROUPS:
                    fps.pop((cid, g), None)
                fps[(cid, "address")] = fact_fingerprint(r, "candidate")  # v2 source backs the address
                r = candidate_from_v2(r, cid, task)
            r = sanitize(r, fname, bulk)
            host = r.get("meets_in_building_of", "")
            r["host_church_id"] = host if host.isdigit() else ""
            r["host_venue_name"] = "" if host.isdigit() else host
            pm = r.get("possible_match_id", "")
            r["possible_match_church_id"] = pm if pm.isdigit() else ""
            r["possible_match_candidate_id"] = "" if pm.isdigit() else pm
            r["duplicate_of_church_id"] = (CANDIDATE_DUPLICATES.get(cid)
                                           or CANDIDATE_DUPLICATES_BY_NAME.get((task, r["candidate_name"]), ""))
            r["last_pass"] = task
            r["source_file"] = fname
            current[cid] = r
    out = sorted(current.values(), key=lambda r: r["candidate_id"])
    write("muse_candidates.csv", CAND_COLS, out)
    return {r["candidate_id"]: r["source_file"] for r in out}, fps


TRANSIENT_HTTP = {"", "408", "425", "429", "500", "502", "503", "504"}  # "" = timeout / connection error
DECISIVE = {"verified", "not_found", "partial", "not_an_excerpt", "source_gone"}  # verdicts that judge the fact
CARRY_DAYS = 30


def load_history(stem: str) -> dict[tuple[str, str, str], list[tuple[str, str]]]:
    """Every (checked_at, verdict) per (row_key, group, fact_fingerprint) in the re-check history."""
    path = RET / "recheck" / "history" / f"{stem}.csv"
    hist: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("fact_fingerprint"):
                    hist.setdefault((r["row_key"], r["group"], r["fact_fingerprint"]), []).append(
                        (r["checked_at"], r["verdict"]))
    return hist


def carry_over(verdict: str, http_status: str, checked_at: str, key: tuple[str, str, str],
               history: dict[tuple[str, str, str], list[tuple[str, str]]]) -> tuple[str, str, bool]:
    """Keep a recent 'verified' through a transient fetch failure, and only then.

    - The latest check couldn't fetch the page for a transient reason (timeout,
      connection error, 408/425/429/5xx). A 404/410 is 'source_gone' and never carries.
    - The fact is the one verified (same fingerprint).
    - Among earlier checks of that fact, the latest one that actually judged it
      (verified / not_found / partial / not_an_excerpt / source_gone) is 'verified':
      verified -> not_found -> fetch_failed stays unverified.
    - That verification is at most CARRY_DAYS old.
    Returns (verdict, checked_at, carried); checked_at is then the verification relied on."""
    if verdict != "fetch_failed" or str(http_status or "") not in TRANSIENT_HTTP or not checked_at:
        return verdict, checked_at, False
    decisive = [(t, v) for t, v in history.get(key, []) if v in DECISIVE and t and t <= checked_at]
    if not decisive:
        return verdict, checked_at, False
    last_t, last_v = max(decisive)
    if last_v != "verified":
        return verdict, checked_at, False
    try:
        age = datetime.fromisoformat(checked_at.replace("Z", "+00:00")) - datetime.fromisoformat(last_t.replace("Z", "+00:00"))
    except ValueError:
        return verdict, checked_at, False
    if timedelta(0) <= age <= timedelta(days=CARRY_DAYS):
        return "verified", last_t, True
    return verdict, checked_at, False


def build_source_checks(church_files: dict[str, str], cand_files: dict[str, str],
                        fps: dict[tuple[str, str], str], used: dict | None = None) -> None:
    """Attach re-check verdicts to the facts they were made for.

    A verdict counts only if its fact fingerprint equals the fingerprint of the row
    being published (value + source URL + excerpt). Otherwise it is "stale": a
    correction made after the check must be re-checked, not inherit "verified".
    """
    rows, missing, stale, carried_n = [], set(), 0, 0
    for subject_type, files in (("church", church_files), ("candidate", cand_files)):
        by_file: dict[str, list[str]] = {}
        for sid, fname in files.items():
            by_file.setdefault(fname, []).append(sid)
        for fname, sids in by_file.items():
            path = RET / "recheck" / f"{Path(fname).stem}.csv"
            if not path.exists():
                missing.add(fname)
                continue
            wanted = set(sids)
            history = load_history(Path(fname).stem)
            with path.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    key = r["row_key"]
                    if subject_type == "candidate" and key.startswith("row"):  # v2 rows are numbered
                        key = f"{fname.split('_')[-1][0]}-{int(key[3:]):02d}"
                    if key not in wanted:
                        continue
                    group = "address" if r["group"] == "candidate" else r["group"]
                    if (subject_type, key, group) in (used or {}):
                        continue  # this fact now comes from an S/W answer, checked below
                    current_fp = fps.get((key, group))
                    if current_fp is None:  # that fact is no longer in the row
                        continue
                    verdict, checked_at, carried = r["verdict"], r["checked_at"], False
                    if r.get("fact_fingerprint") != current_fp:
                        verdict, stale = "stale", stale + 1
                    else:
                        verdict, checked_at, carried = carry_over(
                            verdict, r.get("http_status", ""), checked_at, (r["row_key"], r["group"], current_fp), history)
                        carried_n += carried
                    rows.append({"subject_type": subject_type, "subject_id": key, "fact_group": group,
                                 "verdict": verdict, "http_status": r["http_status"],
                                 "match_mode": r["match_mode"], "checked_at": checked_at,
                                 "carried_over": "true" if carried else "false"})
    # Facts owned by an S/W answer: verdict from that file's own check, bound to the answer.
    overlay_checks: dict[str, dict] = {}
    for (subject_type, sid, group), (fname, check_group, o) in sorted((used or {}).items()):
        stem = Path(fname).stem
        if stem not in overlay_checks:
            path = RET / "recheck" / f"{stem}.csv"
            overlay_checks[stem] = {}
            if path.exists():
                with path.open(encoding="utf-8") as f:
                    overlay_checks[stem] = {(r["row_key"], r["group"]): r for r in csv.DictReader(f)}
            else:
                missing.add(fname)
        r = overlay_checks[stem].get((sid, check_group))
        if r is None:
            continue
        fp = fact_fingerprint(o, check_group)
        verdict, checked_at, carried = r["verdict"], r["checked_at"], False
        if r.get("fact_fingerprint") != fp:
            verdict, stale = "stale", stale + 1
        else:
            verdict, checked_at, carried = carry_over(verdict, r.get("http_status", ""), checked_at,
                                                      (sid, check_group, fp), load_history(stem))
            carried_n += carried
        rows.append({"subject_type": subject_type, "subject_id": sid, "fact_group": group,
                     "verdict": verdict, "http_status": r["http_status"], "match_mode": r["match_mode"],
                     "checked_at": checked_at, "carried_over": "true" if carried else "false"})
    write("source_checks.csv", ["subject_type", "subject_id", "fact_group", "verdict", "http_status",
                                "match_mode", "checked_at", "carried_over"], rows)
    if carried_n:
        print(f"  {carried_n} verdicts carried over a transient fetch failure (verified within {CARRY_DAYS} days)")
    if stale:
        print(f"  WARNING: {stale} re-check verdicts are stale (fact changed or checked before "
              f"fingerprints existed); those facts stay hidden until recheck_sources.py runs again.")
    for fname in sorted(missing):
        print(f"  WARNING: no re-check for {fname}: its web facts stay hidden. Run:\n"
              f"    analytics/.venv/bin/python analytics/scripts/recheck_sources.py {RET / fname}")


def _norm_url(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("http://", "").replace("https://", "").replace("www.", ""))


# ---------------------------------------------------------------- audit grading
# Complete, normalized comparisons (review of PR #41, issue 3). Anything that can't
# be compared confidently is "needs_review", never "agree".

TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z])", re.I)
BARE_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b(?!\s*[ap]\.?\s?m)", re.I)


def parse_times(text: str) -> set[str] | None:
    """Times as 24h HH:MM. None if any time lacks AM/PM (can't compare)."""
    t = text.lower()
    found = set()
    for h, m, ap in TIME_RE.findall(t):
        hour = int(h) % 12 + (12 if ap.startswith("p") else 0)
        found.add(f"{hour:02d}:{int(m or 0):02d}")
    if BARE_TIME_RE.search(TIME_RE.sub(" ", t)):
        return None
    return found


def grade_service_times(auditor: str, muse: str) -> str:
    a, m = parse_times(auditor), parse_times(muse)
    if a is None or m is None or not a or not m:
        return "needs_review"
    return "agree" if a <= m else "disagree"  # every time the auditor found is in Muse's answer


STREET_SUFFIX = {"street": "st", "st": "st", "avenue": "ave", "ave": "ave", "av": "ave", "boulevard": "blvd",
                 "blvd": "blvd", "drive": "dr", "dr": "dr", "road": "rd", "rd": "rd", "lane": "ln", "ln": "ln",
                 "court": "ct", "ct": "ct", "way": "way", "place": "pl", "pl": "pl", "circle": "cir",
                 "cir": "cir", "highway": "hwy", "hwy": "hwy", "real": "real", "parkway": "pkwy", "pkwy": "pkwy",
                 "terrace": "ter", "ter": "ter"}
DIRECTION = {"north": "n", "n": "n", "south": "s", "s": "s", "east": "e", "e": "e", "west": "w", "w": "w"}


def parse_street(text: str) -> tuple[str, tuple[str, ...], str | None] | None:
    """(house number, normalized street tokens, ZIP or None). None if no house number."""
    t = text.lower().replace("\n", ", ").replace(".", "")  # "W. 42nd" -> "w 42nd"; lines end a part
    t = re.sub(r"[^a-z0-9\s,]", " ", t)
    m = re.search(r"\b(\d+)\s+([a-z0-9 ]+?)\s*(?:,|$)", t)
    if not m:
        return None
    tokens, street = m.group(2).split(), []
    for tok in tokens:
        tok = DIRECTION.get(tok, STREET_SUFFIX.get(tok, tok))
        street.append(tok)
        if tok in STREET_SUFFIX.values():
            break
    zips = re.findall(r"\b(9\d{4})(?:\s*\d{4})?\b", t)
    return m.group(1), tuple(street), (zips[-1] if zips else None)


def grade_street(auditor: str, muse: str) -> str:
    a, m = parse_street(auditor), parse_street(muse)
    if a is None or m is None:
        return "needs_review"
    if a[0] != m[0] or a[1] != m[1]:
        return "disagree"
    if a[2] and m[2] and a[2] != m[2]:
        return "disagree"
    return "agree"


def grade_phone(auditor: str, muse: str) -> str:
    a, m = re.sub(r"\D", "", auditor)[-10:], re.sub(r"\D", "", muse)[-10:]
    if len(a) < 10 or len(m) < 10:
        return "needs_review"
    return "agree" if a == m else "disagree"


# Owner verdicts the mechanical comparison cannot make on its own (76692: the old
# congregation closed and was replanted as Bridge City Church; both answers are true).
DEFINITION_DISAGREEMENTS = {("76692", "status"), ("76692", "service_times")}


def build_reviews() -> None:
    key_rows, ws_rows = read("audit_key.csv"), read("audit_worksheet.csv")
    out = []
    if key_rows and ws_rows:
        key = {(r["church_id"], r["field"]): r for r in key_rows}
        for r in ws_rows:
            ans = (r.get("your_answer") or "").strip()
            if not ans:
                continue
            mv = key[(r["church_id"], r["field"])]["muse_value"]
            f = r["field"]
            if (r["church_id"], f) in DEFINITION_DISAGREEMENTS:
                verdict = "definition_disagreement"
            elif f == "pin":
                verdict = "agree" if (ans == "at_building") == (mv == "matches") else "disagree"
            elif f == "phone":
                verdict = grade_phone(ans, mv)
            elif f == "street_address":
                verdict = grade_street(ans, mv)
            elif f == "official_url":
                verdict = "agree" if _norm_url(ans).rstrip("/") == _norm_url(mv).rstrip("/") or (ans.lower() == "none" and not mv) else "disagree"
            elif f == "service_times":
                verdict = grade_service_times(ans, mv)
            else:
                verdict = "agree" if ans.lower() == mv.lower() else "disagree"
            out.append({
                "review_id": f"{r['church_id']}-{f}", "church_id": r["church_id"], "stratum": r["stratum"],
                "field": f, "auditor_value": ans.replace("\n", " ").strip(), "muse_value": mv,
                "verdict": verdict, "evidence_url": r.get("evidence_url", ""), "reviewer": "yujun",
                "reviewed_on": "2026-10-19",
            })
    write("quality_reviews.csv", ["review_id", "church_id", "stratum", "field", "auditor_value",
                                  "muse_value", "verdict", "evidence_url", "reviewer", "reviewed_on"], out)


GEOCODE_COLS = ["geo_id", "subject_type", "subject_id", "status", "latitude", "longitude", "match_type",
                "matched_address", "tiger_line_id", "side", "distance_from_current_pin_m", "geocoded_at",
                "geocoded_street", "geocoded_city", "geocoded_zip", "input_sha256"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_geocodes() -> None:
    """Census pins, each bound to the address it was geocoded from. The input is the
    one whose sha256 the run recorded: the reconciliation receipt if it describes the
    current output, else the original batch's metadata. No matching input, no pins."""
    rows = []
    output = EXPORTS / "geocode_output.csv"
    recon, meta = EXPORTS / "geocode_reconciliation.json", EXPORTS / "geocode_census_metadata.json"
    digest = None
    if output.exists() and recon.exists():
        receipt = json.loads(recon.read_text(encoding="utf-8"))
        if receipt.get("output_sha256") == _sha256(output):
            digest = receipt["input_sha256"]
    if output.exists() and digest is None and meta.exists():
        digest = json.loads(meta.read_text(encoding="utf-8"))["input_sha256"]
    source = next((p for p in sorted(EXPORTS.glob("geocode_input*.csv")) if digest and _sha256(p) == digest), None)
    if output.exists() and source is None:
        print("  WARNING: geocode_output.csv has no input with the sha256 its run recorded; no pins used")
    if source is not None:
        with source.open(encoding="utf-8-sig") as f:
            asked = {r["geo_id"]: r for r in csv.DictReader(f)}
        with output.open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                a = asked.get(r["geo_id"])
                if a is None:
                    continue
                subject_type, subject_id = r["geo_id"].split(":", 1)
                rows.append({**r, "subject_type": subject_type, "subject_id": subject_id,
                             "geocoded_street": a["street"], "geocoded_city": a["city"],
                             "geocoded_zip": a["zip"], "input_sha256": digest})
    write("geocodes.csv", GEOCODE_COLS, rows)


def build_dedup() -> None:
    with (ROOT / "dedup_report.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    write("dedup_candidates.csv", list(rows[0]), rows)


def main() -> None:
    global RET
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--returns", type=Path, default=RET, help="directory holding the Muse returns")
    RET = ap.parse_args().returns.resolve()
    SEEDS.mkdir(parents=True, exist_ok=True)
    batch_of = build_manifest()
    overlays, used = load_overlays(), {}
    church_files, church_fps = build_results(batch_of, overlays, used)
    cand_files, cand_fps = build_candidates(overlays, used)
    build_source_checks(church_files, cand_files, {**church_fps, **cand_fps}, used)
    if used:
        n_s = sum(1 for k in used if k[2] == "service")
        print(f"  overlays applied: {n_s} service answers (S), "
              f"{len(overlays[1]) - len(STALE_W)} verified worship answers (W), "
              f"{sum(1 for k in used if k[2] == 'address')} of them with a corrected street")
    if STALE_W:
        print(f"  WARNING: {len(STALE_W)} W answers are for an address the record no longer has; not used, "
              f"ask again: {', '.join(f'{t}:{i}' for t, i in sorted(STALE_W))}")
    build_reviews()
    build_dedup()
    build_geocodes()


if __name__ == "__main__":
    main()
