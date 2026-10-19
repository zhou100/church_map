"""Build committed dbt seeds from the gitignored Muse returns.

Reads muse_handoff/returns/*.csv (raw returns contain verbatim website and
Facebook excerpts and must stay out of git) and writes sanitized seeds to
analytics/dbt/seeds/:

  muse_manifest.csv        the 77-row Peninsula seed manifest (public OSM data)
  muse_results.csv         current Muse verdict per church: no *_excerpt, no notes;
                           personal phones (D-2) removed; checked_at reliability flag
  muse_candidates.csv      new congregations from batches A and B, no excerpts/notes
  quality_reviews.csv      the owner's blind audit, scored against Muse's answers
  dedup_candidates.csv     May dedup report (OSM duplicate pairs)

Static seeds (denomination_scope.csv, fact_holds.csv) are hand-maintained.

    python3 analytics/scripts/build_seeds.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RET = ROOT / "muse_handoff" / "returns"
SEEDS = ROOT / "analytics" / "dbt" / "seeds"

sys.path.insert(0, str(ROOT / "muse_handoff"))
from validate_returns import NEGATED_PERSONAL_RE, PERSONAL_PHONE_RE  # noqa: E402

# checked_at values the batch A run log admits were reconstructed after the fact.
UNRELIABLE_STAMPS = {"2026-10-19T17:40:00Z", "2026-10-19T16:55:00Z",
                     "2026-10-19T16:51:38Z", "2026-10-19T16:48:35Z"}

RESULT_COLS = [
    "church_id", "entity_type", "status", "status_source_url", "status_source_type",
    "current_name", "official_url", "url_evidence", "facebook_page_url", "fb_page_evidence",
    "fb_last_post_date", "street_address", "city", "state", "zip", "address_source_url",
    "address_source_type", "address_is_worship_location", "meets_in_building_of", "pin_check",
    "phone", "phone_source_url", "phone_source_type", "service_times_verbatim",
    "service_languages", "service_source_url", "service_source_type", "match_confidence",
    "duplicate_of_church_id", "checked_at", "minutes_spent",
]
CAND_COLS = [
    "candidate_name", "current_name_native", "street_address", "city", "state", "zip",
    "official_url", "facebook_page_url", "fb_page_evidence", "fb_last_post_date", "phone",
    "service_languages", "meets_in_building_of", "possible_match_church_id", "source_url",
    "source_type", "found_via", "checked_at",
]

# Batch B candidate later shown (FB-1) to be church 76692 under its new name.
CANDIDATE_DUPLICATES = {("B_main", "Bridge City Church"): "76692"}


def read(name: str) -> list[dict]:
    with (RET / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write(name: str, cols: list[str], rows: list[dict]) -> None:
    with (SEEDS / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


def last_pass_map() -> dict[str, str]:
    m = {r["church_id"]: "A" for r in read("results_A.csv")}
    m.update({r["church_id"]: "B" for r in read("results_B.csv")})
    m.update({r["church_id"]: "A_redo" for r in read("results_A_redo.csv")})
    # Rows taken from the logged-in Facebook check when building results_A_v3.
    m.update({cid: "A_fbcheck" for cid in ("76673", "76674", "76677", "76678", "76683", "77956")})
    m.update({r["church_id"]: "FB1" for r in read("results_FB.csv")})
    return m


def build_results() -> None:
    passes = last_pass_map()
    out = []
    for r in read("results_current.csv"):
        ctx = NEGATED_PERSONAL_RE.sub("", r["notes"] + " " + r["phone_excerpt"])
        personal = bool(r["phone"]) and bool(PERSONAL_PHONE_RE.search(ctx))
        if personal or "personal number withheld" in r["notes"].lower():
            if r["phone"]:
                r.update(phone="", phone_source_url="", phone_source_type="")
            r["personal_phone_withheld"] = "true"
        else:
            r["personal_phone_withheld"] = "false"
        r["checked_at_reliable"] = "false" if r["checked_at"] in UNRELIABLE_STAMPS else "true"
        if r["checked_at_reliable"] == "false":
            r["checked_at"] = ""
        r["last_pass"] = passes[r["church_id"]]
        out.append(r)
    write("muse_results.csv", RESULT_COLS + ["personal_phone_withheld", "checked_at_reliable", "last_pass"], out)


def build_candidates() -> None:
    out = []
    for batch, fname in (("A_calibration", "new_candidates_A.csv"), ("B_main", "new_candidates_B.csv")):
        for i, r in enumerate(read(fname), 1):
            r["candidate_id"] = f"{batch[0]}-{i:02d}"
            r["batch"] = batch
            r["duplicate_of_church_id"] = CANDIDATE_DUPLICATES.get((batch, r["candidate_name"]), "")
            r["checked_at_reliable"] = "false" if r["checked_at"] in UNRELIABLE_STAMPS else "true"
            if r["checked_at_reliable"] == "false":
                r["checked_at"] = ""
            # meets_in_building_of may hold a church_id or a venue name; split them.
            host = r["meets_in_building_of"]
            r["host_church_id"] = host if host.isdigit() else ""
            r["host_venue_name"] = "" if host.isdigit() else host
            out.append(r)
    cols = ["candidate_id", "batch"] + [c for c in CAND_COLS if c != "meets_in_building_of"]
    write("muse_candidates.csv", cols + ["host_church_id", "host_venue_name", "duplicate_of_church_id", "checked_at_reliable"], out)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("http://", "").replace("https://", "").replace("www.", ""))


# Owner verdicts the mechanical comparison cannot make on its own.
DEFINITION_DISAGREEMENTS = {("76692", "status"), ("76692", "service_times")}


def build_reviews() -> None:
    key = {(r["church_id"], r["field"]): r for r in read("audit_key.csv")}
    out = []
    for r in read("audit_worksheet.csv"):
        ans = (r.get("your_answer") or "").strip()
        if not ans:
            continue
        k = key[(r["church_id"], r["field"])]
        mv = k["muse_value"]
        f = r["field"]
        if (r["church_id"], f) in DEFINITION_DISAGREEMENTS:
            verdict = "definition_disagreement"
        elif f == "pin":
            verdict = "agree" if (ans == "at_building") == (mv == "matches") else "disagree"
        elif f == "phone":
            verdict = "agree" if re.sub(r"\D", "", ans)[-10:] == re.sub(r"\D", "", mv)[-10:] else "disagree"
        elif f == "street_address":
            a, b = re.search(r"\b(\d+)\s+\w", ans), re.search(r"\b(\d+)\s+\w", mv)
            verdict = "agree" if a and b and a.group(1) == b.group(1) else "disagree"
        elif f == "official_url":
            verdict = "agree" if norm(ans).rstrip("/") == norm(mv).rstrip("/") or (ans.lower() == "none" and not mv) else "disagree"
        elif f == "service_times":
            times = re.findall(r"(\d{1,2})[:.]?(\d{2})?\s*(a|p)", ans.lower())
            verdict = "agree" if times and all(f"{h}:{m or '00'}" in re.sub(r"\s", "", mv.lower()).replace("am", ":00am").replace("::", ":")
                                               or f"{h}{'' if not m else ':' + m}" in mv.lower() for h, m, _ in times) else "disagree"
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


def build_static_copies() -> None:
    with (ROOT / "muse_handoff" / "peninsula_seed_v1.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    write("muse_manifest.csv", list(rows[0]), rows)
    with (ROOT / "dedup_report.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    write("dedup_candidates.csv", list(rows[0]), rows)


if __name__ == "__main__":
    SEEDS.mkdir(parents=True, exist_ok=True)
    build_results()
    build_candidates()
    build_reviews()
    build_static_copies()
