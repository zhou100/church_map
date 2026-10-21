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
    assert ds.pull_package(wp, status, recheck=False) == "ingested"
    assert not (drive / "feedback" / "WP-0001.md").exists()


def test_ingested_package_lands_where_build_seeds_finds_it(queue, monkeypatch):
    drive, ret, wp = queue
    monkeypatch.setattr(ds, "validate", lambda *a: (True, ""))
    _deliver(wp)
    status = ds.load_status()
    assert ds.pull_package(wp, status, recheck=False) == "ingested"
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
    args = type("A", (), dict(title="Marin County", state="CA", cities="San Rafael=25, Novato=20",
                              other="Any other Marin city=10", db="", seeds=""))
    ds.cmd_new_discovery(args)  # WP-0001 is taken in status.csv
    task = (ds.OUTBOX / "WP-0002" / "TASK.md").read_text()
    assert "task = WP0002" in task and "| Novato | 20 |" in task and "| Any other Marin city | 10 |" in task
    with pytest.raises(SystemExit):
        ds.parse_caps("San Rafael")
