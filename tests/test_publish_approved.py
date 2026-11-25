"""scripts/publish_approved.py: publish only what the owner approved from one reviewed run."""
from __future__ import annotations

import datetime as dt
import json
import os

import pytest

from scripts import publish_approved as pa

RUN = set()


def decision(subject, reasons=(), kind="insert", changes=None):
    return {"kind": kind, "subject": subject, "church_id": None if kind == "insert" else 1,
            "changes": changes or [["name", "fill", None, "N"]], "reasons": sorted(reasons)}


@pytest.mark.parametrize("reasons, expected", [
    ((), "A"), (("low_match_confidence",), "B"), (("shared_address",), "C"),
    (("shared_address", "low_match_confidence"), "C"), (("possible_match",), None),
    (("replace",), None), (("identity_evidence_missing",), None)])
def test_sections_follow_row_level_reasons(reasons, expected):
    assert pa.section(decision("x", reasons), RUN) == expected


def test_run_level_reasons_do_not_move_a_row_out_of_a_section():
    run = {"d1_write", "auto_limit"}
    assert pa.section(decision("x", run | {"low_match_confidence"}), run) == "B"


def test_only_two_kinds_of_update_are_approvable():
    def update(subject, changes, reasons=()):
        return decision(subject, reasons, kind="update", changes=changes)
    denomination = [["denomination", "replace", "Roman Catholic", "Catholic"]]
    scope = [["scope_status", "fill", None, "out_of_scope"]]
    assert pa.section(update("M-1", denomination, ["replace"]), RUN) == "D"   # Muse row (candidate ref)
    assert pa.section(update("1", scope), RUN) == "E"                       # directory row (church_id)
    assert pa.section(update("1", denomination, ["replace"]), RUN) is None  # directory denomination
    assert pa.section(update("M-1", scope), RUN) is None
    assert pa.section(update("1", [["scope_status", "replace", "pending", "out_of_scope"]], ["replace"]), RUN) is None
    assert pa.section(update("M-1", denomination + [["phone", "fill", None, "1"]], ["replace"]), RUN) is None
    assert pa.section(update("M-1", [["latitude", "replace", 1.0, 2.0]], ["replace"]), RUN) is None
    # Inserts still never carry a D-1 field.
    assert pa.section(decision("x", changes=scope), RUN) is None


# ── Real SQL: the full path from a gate dry run to production rows ─────────────

def _url():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("isolated Postgres DATABASE_URL required")
    url = os.environ["DATABASE_URL"]
    assert "test" in url
    return url


@pytest.fixture
def reviewed_run(tmp_path, monkeypatch):
    """A gate dry run over three new congregations (A, B, C-pair) and one D-1 write."""
    import psycopg
    from scripts import publish_gate as g
    url = _url()
    with psycopg.connect(url, autocommit=True) as con:
        con.execute("CREATE SCHEMA analytics")
        last_log = con.execute("SELECT coalesce(max(id), 0) FROM publish_log").fetchone()[0]
        directory_id = con.execute("INSERT INTO churches (name, source) VALUES ('Approved fixture directory', 'osm') "
                                   "RETURNING church_id").fetchone()[0]
        con.execute("INSERT INTO churches (name, source, external_id, denomination, address, city, state, zip_code, "
                    "latitude, longitude) VALUES ('Epsilon Parish', 'muse', 'ap-d', 'Roman Catholic', '5 E St', "
                    "'Town', 'CA', '94000', 37.5, -122.1)")
        try:
            con.execute("CREATE TABLE analytics.mart_publish_churches (church_id bigint, scope_status text)")
            con.execute("INSERT INTO analytics.mart_publish_churches VALUES (%s, 'out_of_scope')", (directory_id,))
            con.execute("CREATE TABLE analytics.mart_publish_new (external_id text, name text, denomination text, "
                        "address text, city text, state text, zip_code text, latitude double precision, "
                        "longitude double precision, checked_at timestamptz, status_source_url text, "
                        "status_source_type text)")
            new = [("ap-a", "Alpha Church", "1 A St"), ("ap-b", "Beta Church", "2 B St"),
                   ("ap-c1", "Gamma Church", "3 C St"), ("ap-c2", "Delta Church", "3 C St")]
            for ref, name, address in new + [("ap-d", "Epsilon Parish", "5 E St")]:
                con.execute("INSERT INTO analytics.mart_publish_new VALUES (%s, %s, %s, %s, 'Town', 'CA', '94000', "
                            "37.5, -122.1, '2026-11-20T18:00:00Z', 'https://example.org/' || %s, 'website')",
                            (ref, name, "Catholic" if ref == "ap-d" else None, address, ref))
            con.execute("CREATE TABLE analytics.stg_muse_results (church_id bigint, personal_phone_withheld text)")
            con.execute("CREATE TABLE analytics.stg_muse_candidates (candidate_id text, possible_match_church_id bigint, "
                        "possible_match_candidate_id text, match_confidence text, personal_phone_withheld text)")
            for ref, conf in [("ap-a", "high"), ("ap-b", "low"), ("ap-c1", "high"), ("ap-c2", "high")]:
                con.execute("INSERT INTO analytics.stg_muse_candidates VALUES (%s, NULL, NULL, %s, 'no')", (ref, conf))
            monkeypatch.setenv("PUBLISH_DATABASE_URL", url)
            monkeypatch.setenv("ANALYTICS_DATABASE_URL", url)
            monkeypatch.setattr(g, "fetch_health", lambda _: {"read_only": False})
            receipt, results = tmp_path / "receipt.json", tmp_path / "run_results.json"
            receipt.write_text(json.dumps({"as_of_date": "2026-11-20"}))
            results.write_text(json.dumps({"results": [{"status": "pass"}]}))
            directory = tmp_path / "private"
            summary = g.dry_run(directory, receipt, results)
            assert summary["publish_gate"] == "pending"  # the D-1 write holds the whole run
            monkeypatch.setattr(g, "fetch_health", lambda _: {"read_only": False})
            yield con, url, directory, directory_id
        finally:
            con.execute("DROP SCHEMA analytics CASCADE")
            con.execute("DELETE FROM church_fact_sources WHERE church_id IN "
                        "(SELECT church_id FROM churches WHERE external_id LIKE 'ap-%%')")
            con.execute("DELETE FROM publish_log WHERE id > %s", (last_log,))
            con.execute("DELETE FROM churches WHERE external_id LIKE 'ap-%%' OR church_id = %s", (directory_id,))


def _muse(con):
    """The congregations this fixture publishes (ap-d was published before the run)."""
    return dict(con.execute("SELECT external_id, name FROM churches WHERE source = 'muse' "
                            "AND external_id LIKE 'ap-%%' AND external_id <> 'ap-d'").fetchall())


def _updated(con, directory_id):
    return (con.execute("SELECT denomination, verified_by FROM churches WHERE external_id = 'ap-d'").fetchone(),
            con.execute("SELECT scope_status FROM churches WHERE church_id = %s", (directory_id,)).fetchone()[0])


def test_publishes_exactly_the_approved_sections_and_reverts(reviewed_run):
    from scripts import publish_verified as publisher
    con, url, directory, directory_id = reviewed_run
    assert pa.approve(directory, {"A", "C"})["approved"] == 3
    checked = pa.apply_approved(directory, url, write=False, max_age_hours=96)
    assert checked["to_write"] == 3 and _muse(con) == {}
    done = pa.apply_approved(directory, url, write=True, max_age_hours=96)
    assert done["inserted"] == 3
    assert _muse(con) == {"ap-a": "Alpha Church", "ap-c1": "Gamma Church", "ap-c2": "Delta Church"}
    run_id = json.loads((directory / "run.json").read_text())["run_id"]
    row = con.execute("SELECT verified_at, verified_by, latitude FROM churches WHERE external_id = 'ap-a'").fetchone()
    assert row == (dt.datetime(2026, 11, 20, 18, tzinfo=dt.timezone.utc), "muse+recheck", 37.5)
    assert con.execute("SELECT count(*) FROM church_fact_sources WHERE run_id = %s AND field = 'active'",
                       (run_id,)).fetchone()[0] == 3
    # The D-1 write, the denomination update and the unapproved B row were not touched.
    assert _updated(con, directory_id) == (("Roman Catholic", None), None)
    # A resumed apply finds nothing left to do.
    again = pa.apply_approved(directory, url, write=True, max_age_hours=96)
    assert again["already_done"] == 3 and again["to_write"] == 0
    import psycopg
    with psycopg.connect(url, autocommit=True) as prod:
        assert publisher.revert(prod, run_id)["deleted"] == 3
    assert _muse(con) == {}
    with pytest.raises(SystemExit, match="reverted"):
        pa.apply_approved(directory, url, write=True, max_age_hours=96)


@pytest.mark.parametrize("tamper, message", [
    ("plan_value", "reproduce the reviewed diff"),
    ("approval_run", "same reviewed diff"),
    ("approval_subject", "not in an approved section"),
    ("diff", "not the reviewed diff"),
])
def test_refuses_anything_but_the_reviewed_diff(reviewed_run, tamper, message):
    con, url, directory, _ = reviewed_run
    pa.approve(directory, {"A"})
    if tamper == "plan_value":
        plan = json.loads((directory / "plan.json").read_text())
        entry = next(e for e in plan["plan"] if e["subject"] == "ap-a")
        entry["changes"][0][3] = "Changed Name"
        entry["row"]["name"] = "Changed Name"
        (directory / "plan.json").write_text(json.dumps(plan))
    elif tamper in ("approval_run", "approval_subject"):
        approval = json.loads((directory / "approval.json").read_text())
        if tamper == "approval_run":
            approval["run_id"] = "pub-other"
        else:
            approval["subjects"].append("ap-b")  # section B was not approved
        (directory / "approval.json").write_text(json.dumps(approval))
    else:
        diff = next(directory.glob("publish_diff_*.csv"))
        diff.write_text(diff.read_text() + "extra\n")
    with pytest.raises(SystemExit, match=message):
        pa.apply_approved(directory, url, write=True, max_age_hours=96)
    assert _muse(con) == {}


def test_refuses_when_production_moved_on(reviewed_run):
    con, url, directory, _ = reviewed_run
    pa.approve(directory, {"A"})
    con.execute("INSERT INTO publish_log (run_id, church_id, field, action) VALUES ('other-run', 0, '*', 'revert')")
    with pytest.raises(SystemExit, match="since this dry run"):
        pa.apply_approved(directory, url, write=True, max_age_hours=96)
    assert _muse(con) == {}


def test_refuses_a_stale_dry_run_or_read_only_production(reviewed_run, monkeypatch):
    from scripts import publish_gate as g
    con, url, directory, _ = reviewed_run
    pa.approve(directory, {"A"})
    with pytest.raises(SystemExit, match="old"):
        pa.verified_entries(directory, 96, now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=97))
    monkeypatch.setattr(g, "fetch_health", lambda _: {"read_only": True})
    with pytest.raises(SystemExit, match="READ_ONLY"):
        pa.apply_approved(directory, url, write=True, max_age_hours=96)
    monkeypatch.setattr(g, "fetch_health", lambda _: None)
    with pytest.raises(SystemExit, match="unavailable"):
        pa.apply_approved(directory, url, write=True, max_age_hours=96)
    assert _muse(con) == {}


def test_refuses_a_congregation_another_run_published(reviewed_run):
    con, url, directory, _ = reviewed_run
    pa.approve(directory, {"A"})
    con.execute("INSERT INTO churches (name, source, external_id) VALUES ('Alpha Church', 'muse', 'ap-a')")
    with pytest.raises(SystemExit, match="another run"):
        pa.apply_approved(directory, url, write=True, max_age_hours=96)


def test_publishes_approved_updates_and_reverts(reviewed_run):
    import psycopg
    from scripts import publish_verified as publisher
    con, url, directory, directory_id = reviewed_run
    approval = pa.approve(directory, {"D", "E"})
    assert (approval["D"], approval["E"], approval["approved"]) == (1, 1, 2)
    done = pa.apply_approved(directory, url, write=True, max_age_hours=96)
    assert done["updated"] == 2 and _muse(con) == {}
    assert _updated(con, directory_id) == (("Catholic", "muse+recheck"), "out_of_scope")
    again = pa.apply_approved(directory, url, write=True, max_age_hours=96)
    assert again["already_done"] == 2 and again["to_write"] == 0
    run_id = json.loads((directory / "run.json").read_text())["run_id"]
    with psycopg.connect(url, autocommit=True) as prod:
        publisher.revert(prod, run_id)
    assert _updated(con, directory_id) == (("Roman Catholic", None), None)


def test_excluded_subjects_stay_out(reviewed_run):
    con, url, directory, directory_id = reviewed_run
    approval = pa.approve(directory, {"E"}, frozenset({str(directory_id)}))
    assert approval["approved"] == 0 and approval["excluded"] == 1
    assert pa.apply_approved(directory, url, write=True, max_age_hours=96)["to_write"] == 0
    assert _updated(con, directory_id)[1] is None


def test_exclusion_must_name_a_row_of_an_approved_section(reviewed_run):
    _, _, directory, _ = reviewed_run
    with pytest.raises(SystemExit, match="not in an approved section"):
        pa.approve(directory, {"E"}, frozenset({"ap-a"}))


def test_update_refused_when_production_moved_on(reviewed_run):
    con, url, directory, directory_id = reviewed_run
    pa.approve(directory, {"D", "E"})
    con.execute("UPDATE churches SET denomination = 'Hand edited' WHERE external_id = 'ap-d'")
    with pytest.raises(SystemExit, match="changed since the review"):
        pa.apply_approved(directory, url, write=True, max_age_hours=96)
    assert _updated(con, directory_id) == (("Hand edited", None), None)
