"""muse_handoff/drive_sync.py: the Drive work queue between ChurchMap and Muse (no network)."""
import csv
import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ds = _load("drive_sync", _ROOT / "muse_handoff" / "drive_sync.py")
bs = _load("build_seeds_for_drive", _ROOT / "analytics" / "scripts" / "build_seeds.py")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def queue(tmp_path, monkeypatch):
    drive, outbox, ret = tmp_path / "drive", tmp_path / "outbox", tmp_path / "returns"
    for d in (drive / "returns", outbox, ret):
        d.mkdir(parents=True)
    monkeypatch.setattr(ds, "DRIVE", drive)
    monkeypatch.setattr(ds, "OUTBOX", outbox)
    monkeypatch.setattr(ds, "RET", ret)
    monkeypatch.setattr(ds, "STATUS", outbox / "status.csv")
    ds.save_status({"WP-0001": dict(wp_id="WP-0001", title="Marin", state="queued", published_at="x")})
    wp = drive / "returns" / "WP-0001"
    wp.mkdir()
    return drive, ret, wp


def _deliver(wp, body="candidate_ref,task\nWP0001-001,WP0001\n", done=None):
    (wp / "new_candidates.csv").write_text(body, encoding="utf-8")
    (wp / "run_log.md").write_text("log", encoding="utf-8")
    (wp / "DONE.md").write_text(done or (f"new_candidates.csv rows=1 sha256={_sha(wp / 'new_candidates.csv')}\n"
                                         f"run_log.md sha256={_sha(wp / 'run_log.md')}\npartial: no\n"),
                                encoding="utf-8")


def test_parse_done_reads_names_hashes_and_partial():
    a, b = "a" * 64, "b" * 64
    files, partial = ds.parse_done(f"- `new_candidates.csv` — 87 rows — sha256 {a}\nrun_log.md {b}\nPartial: yes\n")
    assert files == {"new_candidates.csv": a, "run_log.md": b} and partial
    assert ds.parse_done(f"old_new_candidates.csv {a}\n") == ({}, False)


def test_started_is_seen_but_nothing_is_read_before_done(queue):
    drive, ret, wp = queue
    (wp / "STARTED.md").write_text("2026-10-21T20:00:00Z")
    status = ds.load_status()
    assert ds.pull_package(wp, status, recheck=False) == "started"
    (wp / "new_candidates.csv").write_text("half written")
    assert ds.pull_package(wp, status, recheck=False) == "started"
    assert not list(ret.glob("*.csv"))


def test_a_file_that_does_not_match_done_is_waited_for(queue, monkeypatch):
    drive, ret, wp = queue
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    _deliver(wp)
    (wp / "new_candidates.csv").write_text("still syncing", encoding="utf-8")
    status = ds.load_status()
    assert ds.pull_package(wp, status, recheck=False).startswith("waiting")
    assert status["WP-0001"]["state"] == "queued" and not (ret / "new_candidates_WP0001.csv").exists()


def test_failed_validation_goes_back_as_feedback_and_is_not_ingested(queue, monkeypatch):
    drive, ret, wp = queue
    monkeypatch.setattr(ds, "validate", lambda *a: (False, "ERROR WP0001-001 task='X' not allowed\n"))
    _deliver(wp)
    status = ds.load_status()
    assert ds.pull_package(wp, status, recheck=False) == "needs_fix"
    assert "task='X'" in (drive / "feedback" / "WP-0001.md").read_text()
    assert not (ret / "new_candidates_WP0001.csv").exists()
    # The same DONE.md is not re-processed; a rewritten one is.
    assert ds.pull_package(wp, status, recheck=False).endswith("(no new DONE.md)")
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    _deliver(wp, body="candidate_ref,task\nWP0001-001,WP0001\nWP0001-002,WP0001\n")
    assert ds.pull_package(wp, status, recheck=False) == "pending_build"
    assert not (drive / "feedback" / "WP-0001.md").exists()


def test_ingested_package_lands_where_build_seeds_finds_it(queue, monkeypatch):
    drive, ret, wp = queue
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    _deliver(wp)
    status = ds.load_status()
    assert ds.pull_package(wp, status, recheck=False) == "pending_build"
    ds.save_status(status)
    assert (ret / "new_candidates_WP0001.csv").exists() and (ret / "run_log_WP0001.md").exists()
    assert (drive / "status.csv").read_text() == (ds.OUTBOX / "status.csv").read_text()
    monkeypatch.setattr(bs, "RET", ret)
    assert bs.package_files("new_candidates") == [("new_candidates_WP0001.csv", "WP0001")]
    assert bs.received_at("new_candidates_WP0001.csv") == status["WP-0001"]["delivered_at"]


def test_unknown_package_is_left_alone(queue):
    drive, ret, wp = queue
    other = drive / "returns" / "WP-0099"
    other.mkdir()
    _deliver(other)
    assert "unknown package" in ds.pull_package(other, ds.load_status(), recheck=False)


def test_known_list_uses_the_pins_around_the_named_cities(tmp_path):
    db = tmp_path / "dir.db"
    con = sqlite3.connect(db)
    con.execute("create table Churches (church_id integer, name text, city text, state text, address text, "
                "website text, latitude real, longitude real)")
    con.executemany("insert into Churches values (?,?,?,?,?,?,?,?)", [
        (1, "St A", "San Rafael", "CA", "1 A St", "", 37.97, -122.53),
        (2, "B Church", "Larkspur", "CA", "2 B St", "", 37.98, -122.54),   # mislabeled neighbour, inside the box
        (3, "C Church", "Fresno", "CA", "3 C St", "", 36.74, -119.78),     # far away
        (4, "D Church", "San Rafael", "NM", "", "", 35.11, -107.88),       # same name, other state
    ])
    con.commit()
    con.close()
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    cols = ["candidate_id", "task", "candidate_name", "current_name_native", "city", "street_address",
            "official_url", "facebook_page_url", "status"]
    with (seeds / "muse_candidates.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerow(dict(candidate_id="F-001", task="F", candidate_name="E Church", current_name_native="",
                        city="San Rafael", street_address="", official_url="", facebook_page_url="", status="active"))
    known = ds.known_congregations("CA", ["San Rafael"], db, seeds)
    assert sorted(k["known_id"] for k in known) == ["1", "2", "F-001"]


def test_new_discovery_numbers_packages_and_writes_the_task(tmp_path, monkeypatch, queue):
    monkeypatch.setattr(ds, "known_congregations", lambda *a: [])
    args = type("A", (), dict(title="Marin County", state="CA", cities="San Rafael=25, Novato=20", note="",
                              other="Any other Marin city=10", db="", seeds=""))
    ds.cmd_new_discovery(args)  # WP-0001 is taken in status.csv
    task = (ds.OUTBOX / "WP-0002" / "TASK.md").read_text()
    assert "task = WP0002" in task and "| Novato | 20 |" in task and "| Any other Marin city | 10 |" in task
    with pytest.raises(SystemExit):
        ds.parse_caps("San Rafael")


# --- lead-checking packages (IRS leads) -----------------------------------------------

def _leads_pkg(outbox, n=3):
    pkg = outbox / "WP-0003"
    pkg.mkdir(parents=True)
    ds.write_csv(pkg / "leads.csv", ds.LEAD_COLS, [dict(lead_id=f"WP0003-{i:03d}") for i in range(1, n + 1)])


def _outcomes(path, rows):
    ds.write_csv(path, ds.OUTCOME_COLS, rows)


def test_every_lead_needs_exactly_one_known_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "OUTBOX", tmp_path)
    _leads_pkg(tmp_path)
    out = tmp_path / "o.csv"
    _outcomes(out, [dict(lead_id="WP0003-001", outcome="no_trace"), dict(lead_id="WP0003-001", outcome="no_trace"),
                    dict(lead_id="WP0003-002", outcome="gone"), dict(lead_id="WP0003-009", outcome="no_trace")])
    errs = "\n".join(ds.check_leads("WP-0003", out, None))
    assert "WP0003-001: 2 outcome rows" in errs and "WP0003-003: no outcome row" in errs
    assert "outcome='gone'" in errs and "WP0003-009: not a lead" in errs


def test_active_lead_needs_evidence_and_a_candidate_row(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "OUTBOX", tmp_path)
    _leads_pkg(tmp_path, n=2)
    out, cands = tmp_path / "o.csv", tmp_path / "c.csv"
    _outcomes(out, [dict(lead_id="WP0003-001", outcome="active", evidence_url="https://a.example"),
                    dict(lead_id="WP0003-002", outcome="already_known", evidence_url="https://b.example")])
    ds.write_csv(cands, ["candidate_ref"], [dict(candidate_ref="WP0003-901")])
    errs = "\n".join(ds.check_leads("WP-0003", out, cands))
    assert "WP0003-001: outcome active but no new_candidates row" in errs
    assert "WP0003-002: outcome already_known needs known_id" in errs
    ds.write_csv(cands, ["candidate_ref"], [dict(candidate_ref="WP0003-001")])
    _outcomes(out, [dict(lead_id="WP0003-001", outcome="active", evidence_url="https://a.example"),
                    dict(lead_id="WP0003-002", outcome="already_known", known_id="77001")])
    assert ds.check_leads("WP-0003", out, cands) == []


il = _load("irs_leads", _ROOT / "analytics" / "scripts" / "irs_leads.py")


def test_irs_matching_by_street_or_near_identical_name_in_the_same_city():
    idx = il.Index()
    idx.add("osm:1", "First Baptist Church of San Rafael", "San Rafael", "1 A Street", "94901")
    idx.add("osm:2", "St. Mary's Catholic Church", "Oakland", "", "")
    assert idx.match("FIRST BAPTIST CHURCH", "SAN RAFAEL", "", "") == ("name", "osm:1")
    assert idx.match("SOMETHING ELSE INC", "SAN RAFAEL", "1 A ST", "94901-1234") == ("street", "osm:1")
    assert idx.match("SAINT MARYS CATHOLIC CHURCH", "OAKLAND", "", "") == ("name", "osm:2")
    assert idx.match("FIRST BAPTIST CHURCH", "NOVATO", "", "") is None


def test_irs_filters_keep_congregations_and_drop_mailboxes(tmp_path):
    cols = ["EIN", "NAME", "STREET", "CITY", "ZIP", "SUBSECTION", "FOUNDATION", "NTEE_CD", "ACTIVITY",
            "GROUP", "RULING"]
    rows = [("1", "GRACE CHURCH", "10 MAIN ST", "OAKLAND", "94601", "03", "10", "", "001000000", "0000", "1980"),
            ("2", "GRACE CHURCH", "PO BOX 5", "OAKLAND", "94601", "03", "10", "", "", "0000", "1980"),
            ("3", "BETH ISRAEL", "1 A ST", "OAKLAND", "94601", "03", "10", "X30", "", "0000", "1980"),
            ("4", "GRACE CHURCH", "10 MAIN ST", "OAKLAND", "94601", "04", "10", "X20", "", "0000", "1980"),
            ("5", "HOPE CHRISTIAN SCHOOL", "2 B ST", "OAKLAND", "94601", "03", "10", "X20", "", "0000", "1980")]
    with (tmp_path / "bmf.csv").open("w", newline="", encoding="latin-1") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    got = {r["EIN"]: r for r in il.bmf_churches(tmp_path / "bmf.csv")}
    assert set(got) == {"1", "2", "5"}  # non-Christian NTEE and non-501(c)(3) dropped
    assert got["2"]["mailbox"] and not got["1"]["mailbox"]
    assert got["1"]["congregation_like"] and not got["5"]["congregation_like"]


def test_late_stamps_do_not_block_a_delivery(queue, monkeypatch):
    drive, ret, wp = queue
    monkeypatch.setattr(ds, "validate", lambda *a: (False, "ERROR X-1 checked_at 2026-10-21T19:23:21Z is after "
                                                          "the file was received (19:19Z)\n"))
    _deliver(wp)
    status = ds.load_status()
    assert ds.pull_package(wp, status, recheck=False) == "pending_build"
    assert "marked unreliable" in status["WP-0001"]["note"]
    monkeypatch.setattr(ds, "validate", lambda *a: (False, "ERROR X-1 checked_at late is after the file was "
                                                          "received\nERROR X-2 missing required city\n"))
    _deliver(wp, body="candidate_ref,task\nWP0001-001,WP0001\nWP0001-002,WP0001\n")
    assert ds.pull_package(wp, status, recheck=False) == "needs_fix"
    assert "missing required city" in (drive / "feedback" / "WP-0001.md").read_text()


# --- Review of 69293de --------------------------------------------------------------

def test_results_are_validated_against_the_manifest_in_the_dashed_package_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "OUTBOX", tmp_path)
    (tmp_path / "WP-0001").mkdir()
    (tmp_path / "WP-0001" / "manifest.csv").write_text("church_id\n1\n")
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return type("P", (), dict(returncode=0, stdout="", stderr=""))()
    monkeypatch.setattr(ds.subprocess, "run", run)
    ok, out = ds.validate("results", tmp_path / "r.csv", "2026-10-21T00:00:00Z", "WP-0001")
    assert ok and str(tmp_path / "WP-0001" / "manifest.csv") in seen["cmd"]


def test_a_failed_build_is_retried_until_it_succeeds(queue, monkeypatch):
    drive, ret, wp = queue
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    _deliver(wp)
    args = type("A", (), dict(again=[], no_recheck=True, no_build=False, no_geocode=True))
    monkeypatch.setattr(ds, "sync_reference", lambda: None)
    monkeypatch.setattr(ds, "rebuild", lambda: "dbt build failed")
    assert ds.cmd_pull(args) == 1
    row = ds.load_status()["WP-0001"]
    assert row["state"] == "build_failed" and "dbt build failed" in row["build_error"]
    # DONE.md is unchanged, yet the next pull rebuilds and only then marks it ingested.
    calls = []
    monkeypatch.setattr(ds, "rebuild", lambda: calls.append(1) or "")
    assert ds.cmd_pull(args) == 0
    row = ds.load_status()["WP-0001"]
    assert calls and row["state"] == "ingested" and row["build_error"] == ""


def test_a_failed_geocode_keeps_the_ingest_and_is_retried_on_every_pull(queue, monkeypatch):
    drive, ret, wp = queue
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    _deliver(wp)
    args = type("A", (), dict(again=[], no_recheck=True, no_build=False, no_geocode=False))
    monkeypatch.setattr(ds, "sync_reference", lambda: None)
    monkeypatch.setattr(ds, "rebuild", lambda: "")
    monkeypatch.setattr(ds, "geocode", lambda: "geocode_incremental.py failed")
    assert ds.cmd_pull(args) == 1
    assert ds.load_status()["WP-0001"]["state"] == "ingested"
    # Nothing new delivered: the next pull still runs the Census step.
    calls = []
    monkeypatch.setattr(ds, "geocode", lambda: calls.append(1) or "")
    assert ds.cmd_pull(args) == 0 and calls


def _geocode_fixture(tmp_path, monkeypatch, results):
    """geocode() with Census mocked; rebuild() returns each of `results` in turn."""
    monkeypatch.setattr(ds, "ROOT", tmp_path)
    out = tmp_path / "analytics/exports/geocode_output.csv"
    out.parent.mkdir(parents=True)
    out.write_text("geo_id\n")
    calls = []
    monkeypatch.setattr(ds, "rebuild", lambda: calls.append(1) or results[len(calls) - 1])
    ok = type("P", (), dict(returncode=0))()
    monkeypatch.setattr(ds.subprocess, "run", lambda cmd, **kw: ok)
    return out, calls, ok


def test_geocode_rebuilds_only_when_the_last_build_read_another_output(tmp_path, monkeypatch):
    out, calls, ok = _geocode_fixture(tmp_path, monkeypatch, ["", "", ""])
    assert ds.geocode() == "" and len(calls) == 1  # never built: build once
    assert ds.geocode() == "" and len(calls) == 1  # same output as the last build
    monkeypatch.setattr(ds.subprocess, "run", lambda cmd, **kw: (out.write_text("geo_id\nchurch:1\n"), ok)[1])
    assert ds.geocode() == "" and len(calls) == 2


def test_a_rebuild_that_failed_after_new_pins_is_retried_with_unchanged_output(tmp_path, monkeypatch):
    # Review of e734ff1: comparing with the output before the run returned success on the
    # second pull and the failed build was never redone.
    out, calls, ok = _geocode_fixture(tmp_path, monkeypatch, ["", "dbt build failed", ""])
    assert ds.geocode() == ""
    monkeypatch.setattr(ds.subprocess, "run", lambda cmd, **kw: (out.write_text("geo_id\nchurch:1\n"), ok)[1])
    assert ds.geocode() == "dbt build failed" and len(calls) == 2
    monkeypatch.setattr(ds.subprocess, "run", lambda cmd, **kw: ok)  # nothing new from Census
    assert ds.geocode() == "" and len(calls) == 3
    assert ds.geocode() == "" and len(calls) == 3


def test_a_successful_rebuild_records_the_output_it_read(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "ROOT", tmp_path)
    out = tmp_path / "analytics/exports/geocode_output.csv"
    out.parent.mkdir(parents=True)
    out.write_text("geo_id\n")
    ok, bad = type("P", (), dict(returncode=0))(), type("P", (), dict(returncode=1))()
    monkeypatch.setattr(ds.subprocess, "run", lambda cmd, **kw: bad if "build" in cmd else ok)
    assert ds.rebuild() == "dbt build failed" and not ds.built_marker().exists()
    monkeypatch.setattr(ds.subprocess, "run", lambda cmd, **kw: ok)
    assert ds.rebuild() == "" and ds.built_marker().read_text().strip() == f"{ds.sha256(out)}|unbound"


def test_a_receipt_fixed_after_a_build_without_binding_rebuilds_with_the_same_output(tmp_path, monkeypatch):
    # Review of 0b692bf: the output was replaced but the interrupted write left the old
    # receipt. The next build finds no binding (no pins) and marks the output built. A
    # later run republishes the same output with its receipt: the output bytes are the
    # same, but the binding is new, so it must rebuild, or the pins stay missing.
    import json
    exports = tmp_path / "analytics/exports"
    exports.mkdir(parents=True)
    inp, out, receipt = exports / "geocode_input_aaaa.csv", exports / "geocode_output.csv", \
        exports / "geocode_reconciliation.json"
    inp.write_text("geo_id,street,city,state,zip\ncandidate:X-1,100 Main St,San Mateo,CA,94401\n")
    out.write_text("geo_id,status,latitude,longitude\ncandidate:X-1,ok,37.5,-122.3\n")
    receipt.write_text(json.dumps({"input_sha256": ds.sha256(inp), "output_sha256": "0" * 64}))  # stale
    monkeypatch.setattr(ds, "ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(ds, "rebuild", lambda: calls.append(ds.geocode_build_key()) or "")
    ok = type("P", (), dict(returncode=0))()
    monkeypatch.setattr(ds.subprocess, "run", lambda cmd, **kw: ok)
    assert ds.geocode() == "" and calls == [f"{ds.sha256(out)}|unbound"]
    receipt.write_text(json.dumps({"input_sha256": ds.sha256(inp), "output_sha256": ds.sha256(out)}))  # fixed
    assert ds.geocode() == "" and calls[-1] == f"{ds.sha256(out)}|{ds.sha256(inp)}" and len(calls) == 2
    assert ds.geocode() == "" and len(calls) == 2  # built with this binding: nothing to do


def test_a_failed_recheck_leaves_the_delivery_to_be_retried(queue, monkeypatch):
    drive, ret, wp = queue
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    _deliver(wp)
    monkeypatch.setattr(ds.subprocess, "run", lambda *a, **k: type("P", (), dict(returncode=1))())
    status = ds.load_status()
    assert ds.pull_package(wp, status, recheck=True).startswith("waiting: source re-check failed")
    assert status["WP-0001"].get("done_sha256", "") == ""


# --- service-fix packages -------------------------------------------------------------

vr = _load("validate_returns_for_drive", _ROOT / "muse_handoff" / "validate_returns.py")


def test_service_fix_validator_names_the_times_the_excerpt_does_not_state(tmp_path, capsys):
    cols = ["subject_type", "subject_id", "service_times_verbatim", "service_languages", "service_source_url",
            "service_source_type", "service_excerpt", "checked_at", "notes"]
    rows = [dict(subject_type="church", subject_id="1", service_times_verbatim="Sunday English Mass 10 AM",
                 service_source_url="https://a.example/mass", service_source_type="own_site",
                 service_excerpt="Sunday Mass 10 AM; Sunday Mass 11 AM (Spanish)", checked_at="2026-10-21T10:00:00Z"),
            dict(subject_type="candidate", subject_id="C-1", service_times_verbatim="Sunday Mass 11 AM (Spanish)",
                 service_source_url="https://b.example/", service_source_type="own_site",
                 service_excerpt="Sunday Mass 11 AM (Spanish)", checked_at="2026-10-21T10:00:00Z")]
    ds.write_csv(tmp_path / "s.csv", cols, rows)
    vr.problems.clear()
    assert vr.main(["x", "--service-fixes", str(tmp_path / "s.csv")]) == 1
    out = capsys.readouterr().out
    assert "church:1" in out and "does not state: Sun 10:00 worship English" in out and "C-1 " not in out


def test_every_service_fix_input_row_must_come_back(queue, monkeypatch):
    drive, ret, wp = queue
    ds.write_csv(ds.OUTBOX / "WP-0001" / "service_fix_input.csv", ds.FIX_INPUT_COLS,
                 [dict(subject_type="church", subject_id="1"), dict(subject_type="candidate", subject_id="C-1")])
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    (wp / "service_fixes.csv").write_text("subject_type,subject_id\nchurch,1\n", encoding="utf-8")
    (wp / "DONE.md").write_text(f"service_fixes.csv sha256={_sha(wp / 'service_fixes.csv')}\n", encoding="utf-8")
    status = ds.load_status()
    assert ds.pull_package(wp, status, recheck=False) == "needs_fix"
    assert "candidate:C-1: no row" in (drive / "feedback" / "WP-0001.md").read_text()


# --- Review of b8898c8 --------------------------------------------------------------

def test_a_lead_package_must_return_lead_outcomes(queue, monkeypatch):
    drive, ret, wp = queue
    ds.write_csv(ds.OUTBOX / "WP-0001" / "leads.csv", ds.LEAD_COLS, [dict(lead_id="WP0001-001")])
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    _deliver(wp)  # new_candidates.csv only
    status = ds.load_status()
    assert ds.pull_package(wp, status, recheck=False) == "needs_fix"
    assert "Missing: this package asks for one outcome per `lead_id`" in (drive / "feedback" / "WP-0001.md").read_text()


def test_a_service_fix_package_must_return_service_fixes(queue, monkeypatch):
    drive, ret, wp = queue
    ds.write_csv(ds.OUTBOX / "WP-0001" / "service_fix_input.csv", ds.FIX_INPUT_COLS,
                 [dict(subject_type="church", subject_id="1")])
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    _deliver(wp)
    assert ds.pull_package(wp, ds.load_status(), recheck=False) == "needs_fix"
    assert "## `service_fixes.csv`" in (drive / "feedback" / "WP-0001.md").read_text()


def test_lead_outcomes_alone_are_accepted_without_a_recheck(queue, monkeypatch):
    drive, ret, wp = queue
    ds.write_csv(ds.OUTBOX / "WP-0001" / "leads.csv", ds.LEAD_COLS, [dict(lead_id="WP0001-001")])
    _outcomes(wp / "lead_outcomes.csv", [dict(lead_id="WP0001-001", outcome="no_trace")])
    (wp / "DONE.md").write_text(f"lead_outcomes.csv sha256={_sha(wp / 'lead_outcomes.csv')}\npartial: no\n",
                                encoding="utf-8")
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    monkeypatch.setattr(ds.subprocess, "run", lambda *a, **k: pytest.fail("nothing cited, nothing to re-check"))
    assert ds.pull_package(wp, ds.load_status(), recheck=True) == "pending_build"



def test_out_of_scope_by_name_needs_a_note_not_a_url(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "OUTBOX", tmp_path)
    _leads_pkg(tmp_path, n=1)
    out = tmp_path / "o.csv"
    _outcomes(out, [dict(lead_id="WP0003-001", outcome="out_of_scope")])
    assert "needs evidence_url, or notes" in "\n".join(ds.check_leads("WP-0003", out, None))
    _outcomes(out, [dict(lead_id="WP0003-001", outcome="out_of_scope", notes="A Baha'i Spiritual Assembly (N8).")])
    assert ds.check_leads("WP-0003", out, None) == []
    _outcomes(out, [dict(lead_id="WP0003-001", outcome="closed", notes="merged, per a podcast")])
    assert "outcome closed needs evidence_url" in "\n".join(ds.check_leads("WP-0003", out, None))



def test_a_lead_outcome_cannot_rest_on_a_directory_listing(tmp_path, monkeypatch):
    # Brief S5: a churchfinder listing doesn't show a congregation meets today.
    monkeypatch.setattr(ds, "OUTBOX", tmp_path)
    _leads_pkg(tmp_path, n=1)
    out = tmp_path / "o.csv"
    _outcomes(out, [dict(lead_id="WP0003-001", outcome="closed",
                         evidence_url="https://www.churchfinder.com/churches/ca/oakland/grace")])
    assert "evidence_url is a church directory" in "\n".join(ds.check_leads("WP-0003", out, None))

# --- Re-check packages: every unresolved new congregation, one row back per ref ----------

def test_recheck_selects_unresolved_new_congregations_closest_to_the_map_first(tmp_path):
    cols = ["candidate_id", "task", "candidate_name", "city", "status", "street_address", "official_url",
            "duplicate_of_church_id", "possible_match_church_id", "possible_match_candidate_id"]
    rows = [dict(candidate_id="A-1", task="D", status="unresolved", street_address="", official_url=""),
            dict(candidate_id="A-2", task="D", status="unresolved", street_address="1 Main", official_url="x"),
            dict(candidate_id="A-3", task="D", status="active", street_address="1 Main", official_url="x"),
            dict(candidate_id="A-4", task="D", status="unresolved", duplicate_of_church_id="7"),
            dict(candidate_id="A-5", task="D", status="unresolved", possible_match_church_id="8"),
            dict(candidate_id="A-6", task="D", status="unresolved", possible_match_candidate_id="C-1"),
            dict(candidate_id="A-7", task="F", status="unresolved", street_address="", official_url="y")]
    with (tmp_path / "muse_candidates.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, restval="")
        w.writeheader()
        w.writerows(rows)
    out = ds.recheck_rows(tmp_path)
    assert [r["candidate_ref"] for r in out] == ["A-2", "A-7", "A-1"]
    assert out[1]["origin_task"] == "F" and list(out[0]) == ds.RECHECK_INPUT_COLS


def test_recheck_return_needs_exactly_the_input_refs_under_this_task(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "OUTBOX", tmp_path)
    (tmp_path / "WP-0014").mkdir()
    ds.write_csv(tmp_path / "WP-0014" / "recheck_input.csv", ds.RECHECK_INPUT_COLS,
                 [dict(candidate_ref="D-001"), dict(candidate_ref="WP0006-001")])
    out = tmp_path / "new_candidates.csv"
    ds.write_csv(out, ["candidate_ref", "task"], [dict(candidate_ref="D-001", task="WP0014"),
                                                   dict(candidate_ref="WP0006-001", task="WP0014")])
    assert ds.check_recheck("WP-0014", out) == []
    ds.write_csv(out, ["candidate_ref", "task"], [dict(candidate_ref="D-001", task="D"),
                                                   dict(candidate_ref="D-001", task="WP0014"),
                                                   dict(candidate_ref="WP0014-001", task="WP0014")])
    errs = "\n".join(ds.check_recheck("WP-0014", out))
    assert "D-001: 2 rows" in errs and "WP0006-001: no row" in errs
    assert "WP0014-001: not in recheck_input.csv" in errs and "task='D', want WP0014" in errs


def test_an_interrupted_publication_then_a_delivery_still_ends_with_the_pins(queue, tmp_path, monkeypatch):
    # Review of 0b692bf, end to end through cmd_pull(): publish() was interrupted (new
    # output, stale receipt). The pull first rebuilds for the delivered package, which
    # correctly finds no binding (no pins). The Census step then repairs the receipt with
    # byte-identical output. The pull must rebuild again and end with the pin in the seed.
    import json
    spec = importlib.util.spec_from_file_location(
        "build_seeds_for_pull_test", Path(__file__).resolve().parents[1] / "analytics/scripts/build_seeds.py")
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)
    drive, ret, wp = queue
    exports, seeds = tmp_path / "analytics/exports", tmp_path / "seeds"
    exports.mkdir(parents=True)
    seeds.mkdir()
    monkeypatch.setattr(bs, "EXPORTS", exports)
    monkeypatch.setattr(bs, "SEEDS", seeds)
    inp, out, receipt = exports / "geocode_input_aaaa.csv", exports / "geocode_output.csv", \
        exports / "geocode_reconciliation.json"
    inp.write_text("geo_id,street,city,state,zip\ncandidate:X-1,100 Main St,San Mateo,CA,94401\n")
    out.write_text("geo_id,status,latitude,longitude\ncandidate:X-1,ok,37.5,-122.3\n")
    receipt.write_text(json.dumps({"input_sha256": ds.sha256(inp), "output_sha256": "0" * 64}))  # torn write

    seed_builds = []
    ok = type("P", (), dict(returncode=0, stdout="", stderr=""))()

    def run(cmd, **kw):
        cmd = [str(c) for c in cmd]
        if any(c.endswith("build_seeds.py") for c in cmd):
            bs.build_geocodes()
            seed_builds.append(len(list(csv.DictReader((seeds / "geocodes.csv").open(encoding="utf-8")))))
        elif any(c.endswith("geocode_incremental.py") for c in cmd):  # republishes: same output, its receipt
            receipt.write_text(json.dumps({"input_sha256": ds.sha256(inp), "output_sha256": ds.sha256(out)}))
        return ok
    monkeypatch.setattr(ds, "ROOT", tmp_path)
    monkeypatch.setattr(ds.subprocess, "run", run)
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    monkeypatch.setattr(ds, "sync_reference", lambda: None)
    _deliver(wp)
    args = type("A", (), dict(again=[], no_recheck=True, no_build=False, no_geocode=False))
    assert ds.cmd_pull(args) == 0
    assert ds.load_status()["WP-0001"]["state"] == "ingested"
    assert seed_builds == [0, 1]  # the package's build had no binding; the receipt repair rebuilt with the pin
    assert ds.cmd_pull(args) == 0 and seed_builds == [0, 1]  # nothing changed since: no rebuild


# --- v3.4 D12: discovery packages report their directory sweep -------------------------

def test_check_sweep_needs_both_directories(tmp_path):
    log = tmp_path / "run_log.md"
    assert ds.check_sweep(log) == "run_log.md is missing"
    log.write_text("Sacramento — churchfinder: listed 212, already known 140, reported 25\n")
    assert "oursweb" in ds.check_sweep(log)
    log.write_text("Sacramento — Churchfinder: listed 212, already known 140, reported 25; "
                   "oursweb: listed 9, already known 6, reported 2\n")
    assert ds.check_sweep(log) == ""


def test_only_discovery_packages_from_wp0020_are_held_to_the_sweep(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "OUTBOX", tmp_path)
    for wp, files in (("WP-0020", ["known_congregations.csv"]), ("WP-0021", ["known_congregations.csv", "leads.csv"]),
                      ("WP-0022", ["recheck_input.csv"])):
        (tmp_path / wp).mkdir()
        for f in files:
            (tmp_path / wp / f).write_text("x\n")
    assert ds.is_discovery("WP-0020") and not ds.is_discovery("WP-0021") and not ds.is_discovery("WP-0022")


def test_the_discovery_template_asks_for_the_sweep():
    text = ds.DISCOVERY_TASK.format(wp_id="WP-0099", task="WP0099", title="t", city_rows="| A | 1 |", known_n=1,
                                    known_sha="x", note="")
    assert "(v3.4)" in text and "churchfinder.com" in text and "church.oursweb.net" in text
    assert "churchfinder: listed N" in text and "church_directory" in text


def test_recheck_can_be_limited_to_the_packages_that_first_reported_the_rows(tmp_path):
    cols = ["candidate_id", "task", "candidate_name", "city", "status", "street_address", "official_url",
            "duplicate_of_church_id", "possible_match_church_id", "possible_match_candidate_id"]
    rows = [dict(candidate_id="WP0011-001", task="WP0011", status="unresolved"),
            dict(candidate_id="WP0006-001", task="WP0006", status="unresolved"),  # re-checked by WP0019 already
            dict(candidate_id="WP0012-001", task="WP0012", status="unresolved")]
    with (tmp_path / "muse_candidates.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, restval="")
        w.writeheader()
        w.writerows(rows)
    assert [r["candidate_ref"] for r in ds.recheck_rows(tmp_path, {"WP0011", "WP0012"})] == ["WP0011-001", "WP0012-001"]
    assert len(ds.recheck_rows(tmp_path)) == 3


def test_the_recheck_template_carries_the_note_and_the_intro():
    fmt = dict(wp_id="WP-0099", task="WP0099", title="t", n=1, sha="x")
    text = ds.RECHECK_TASK.format(**fmt, intro=ds.RECHECK_INTRO["unverified_active"].format(n=1),
                                  note="\n**Why these rows:** Facebook pass.\n")
    assert "(v3.4)" in text and "**Why these rows:** Facebook pass." in text and "`activity_check`" in text
    plain = ds.RECHECK_TASK.format(**fmt, intro=ds.RECHECK_INTRO["unresolved"].format(n=1), note="")
    assert "**Why these rows**" not in plain and "`status = unresolved`" in plain


def test_unverified_active_mode_selects_active_rows_whose_evidence_did_not_hold_up(tmp_path):
    cols = ["candidate_id", "task", "candidate_name", "city", "status", "status_source_type", "street_address",
            "official_url", "duplicate_of_church_id", "possible_match_church_id", "possible_match_candidate_id"]
    rows = [dict(candidate_id="A-1", task="F", status="active", status_source_type="own_site"),  # verified
            dict(candidate_id="A-2", task="F", status="active", status_source_type="own_site"),  # not_found
            dict(candidate_id="A-3", task="F", status="active", status_source_type="fb_page"),   # D-3, left out
            dict(candidate_id="A-4", task="F", status="active", status_source_type="other"),     # aggregator
            dict(candidate_id="A-5", task="F", status="unresolved", status_source_type="own_site"),
            dict(candidate_id="A-6", task="F", status="active", status_source_type="denomination")]  # no check
    for name, header, body in (("muse_candidates.csv", cols, rows),
                               ("source_checks.csv", ["subject_type", "subject_id", "fact_group", "verdict"],
                                [dict(subject_type="candidate", subject_id="A-1", fact_group="status", verdict="verified"),
                                 dict(subject_type="candidate", subject_id="A-2", fact_group="status", verdict="not_found"),
                                 dict(subject_type="candidate", subject_id="A-4", fact_group="status", verdict="verified"),
                                 dict(subject_type="candidate", subject_id="A-2", fact_group="address", verdict="verified")])):
        with (tmp_path / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header, restval="")
            w.writeheader()
            w.writerows(body)
    out = ds.recheck_rows(tmp_path, mode="unverified_active")
    assert [(r["candidate_ref"], r["activity_check"]) for r in out] == \
        [("A-2", "not_found"), ("A-4", "other_source"), ("A-6", "no_check")]
    assert [r["candidate_ref"] for r in ds.recheck_rows(tmp_path)] == ["A-5"]