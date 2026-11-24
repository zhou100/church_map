"""scripts/restore_denomination.py: put back directory denominations the extractor overwrote."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3

import pytest

from scripts import restore_denomination as rd

T = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
MAP = {"islamic": "out_of_scope", "mormon": "in_scope_labeled"}


def test_build_restores_only_what_the_extractor_changed():
    base = {1: "Islamic", 2: None, 3: "Baptist", 4: "Roman Catholic", 5: "Mormon", 6: "Lutheran"}
    rows = [
        (1, "Masjid", "", "", "osm", "Islam", None, T),             # changed: restore, scope back
        (2, "Grace", "", "", "osm", "Non-denominational", None, T),  # filled: restore to NULL
        (3, "First", "", "", "osm", "Southern Baptist", None, None),  # never extracted: other writer
        (4, "Muse", "", "", "muse", "Catholic", None, T),           # publisher's row
        (5, "Ward", "", "", "osm", "The Church of Jesus Christ of Latter-day Saints", "LDS", T),
        (6, "Same", "", "", "osm", " Lutheran ", None, T),
        (7, "New", "", "", "osm", "Baptist", None, T),
    ]
    plan, counts = rd.build(rows, base, MAP)
    assert [p["church_id"] for p in plan] == [1, 2, 5]
    assert counts | {} == {"production_rows": 7, "muse_skipped": 1, "not_in_baseline": 1, "same": 1,
                           "untouched_by_extractor": 1, "restore": 3, "restore_to_null": 1,
                           "keep_newer_reading": 1, "scope_changes_back": 2}
    by_id = {p["church_id"]: p for p in plan}
    assert by_id[1]["extracted_after"] == "Islam" and by_id[1]["baseline_scope"] == "out_of_scope"
    assert by_id[2]["baseline"] is None and by_id[2]["kind"] == "filled"
    assert by_id[5]["extracted_after"] == "LDS"  # a reading written since 0009 is kept


# ── Real SQL ───────────────────────────────────────────────────────────────────

@pytest.fixture
def prod(tmp_path):
    import psycopg
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("isolated Postgres DATABASE_URL required")
    url = os.environ["DATABASE_URL"]
    assert "test" in url
    con = psycopg.connect(url, autocommit=True)
    rows = [("Restore masjid", "osm", "Islam", None, T), ("Restore grace", "osm", "Non-denominational", None, T),
            ("Restore other writer", "osm", "Southern Baptist", None, None),
            ("Restore muse", "muse", "Catholic", None, T),
            ("Restore ward", "osm", "The Church of Jesus Christ of Latter-day Saints", "LDS", T)]
    ids = [con.execute("insert into churches (name, source, denomination, extracted_denomination, extracted_at) "
                       "values (%s, %s, %s, %s, %s) returning church_id", r).fetchone()[0] for r in rows]
    sqlite_path = tmp_path / "baseline.db"
    lite = sqlite3.connect(sqlite_path)
    lite.execute("create table churches (church_id integer, denomination text)")
    lite.executemany("insert into churches values (?, ?)",
                     zip(ids, ["Islamic", None, "Baptist", "Roman Catholic", "Mormon"]))
    lite.commit()
    lite.close()
    try:
        yield con, url, ids, sqlite_path, tmp_path / "private"
    finally:
        con.execute("delete from publish_log where church_id = any(%s)", (ids,))
        con.execute("delete from churches where church_id = any(%s)", (ids,))
        con.close()


def _state(con, ids):
    return [con.execute("select denomination, extracted_denomination from churches where church_id = %s",
                        (i,)).fetchone() for i in ids]


def _only(con, ids, monkeypatch):
    """Plan over the fixture rows only (the test database may hold others)."""
    real = rd.read_production
    monkeypatch.setattr(rd, "read_production", lambda prod: [r for r in real(prod) if r[0] in ids])


def test_plan_apply_and_revert(prod, monkeypatch):
    import psycopg
    from scripts import publish_verified as publisher
    con, url, ids, sqlite_path, out = prod
    _only(con, ids, monkeypatch)
    before = _state(con, ids)
    with psycopg.connect(url, autocommit=True) as p:
        planned = rd.make_plan(p, sqlite_path, out)
    assert planned["restore"] == 3 and planned["untouched_by_extractor"] == 1 and planned["muse_skipped"] == 1
    assert _state(con, ids) == before  # planning writes nothing
    run_dir = out / planned["run_id"]
    assert (run_dir / "review.csv").stat().st_mode & 0o777 == 0o600
    doc = rd.verified_plan(run_dir, sqlite_path)
    with psycopg.connect(url, autocommit=True) as p:
        result = rd.apply(p, doc)
    assert result == {"run_id": planned["run_id"], "restored": 3, "reading_kept": 1, "skipped_changed_since_review": 0}
    assert _state(con, ids) == [("Islamic", "Islam"), (None, "Non-denominational"), ("Southern Baptist", None),
                                ("Catholic", None), ("Mormon", "LDS")]
    with psycopg.connect(url, autocommit=True) as p:
        with pytest.raises(SystemExit, match="already been applied"):
            rd.apply(p, doc)
        assert publisher.revert(p, planned["run_id"])["restored"] == 5
    assert _state(con, ids) == before


def test_a_row_changed_since_review_is_skipped(prod, monkeypatch):
    import psycopg
    con, url, ids, sqlite_path, out = prod
    _only(con, ids, monkeypatch)
    with psycopg.connect(url, autocommit=True) as p:
        planned = rd.make_plan(p, sqlite_path, out)
    con.execute("update churches set denomination = 'Hand edited' where church_id = %s", (ids[0],))
    with psycopg.connect(url, autocommit=True) as p:
        result = rd.apply(p, rd.verified_plan(out / planned["run_id"], sqlite_path))
    assert result["restored"] == 2 and result["skipped_changed_since_review"] == 1
    assert _state(con, ids)[0] == ("Hand edited", None)


@pytest.mark.parametrize("tamper, message", [
    ("review", "not the reviewed file"), ("plan", "does not reproduce"), ("baseline", "not the file")])
def test_apply_refuses_anything_but_the_reviewed_plan(prod, monkeypatch, tamper, message):
    import psycopg
    con, url, ids, sqlite_path, out = prod
    _only(con, ids, monkeypatch)
    with psycopg.connect(url, autocommit=True) as p:
        run_dir = out / rd.make_plan(p, sqlite_path, out)["run_id"]
    if tamper == "review":
        path = run_dir / "review.csv"
        path.write_text(path.read_text() + "extra\n")
    elif tamper == "plan":
        doc = json.loads((run_dir / "plan.json").read_text())
        doc["plan"][0]["baseline"] = "Something else"
        (run_dir / "plan.json").write_text(json.dumps(doc))
    else:
        lite = sqlite3.connect(sqlite_path)
        lite.execute("update churches set denomination = 'Edited' where church_id = ?", (ids[0],))
        lite.commit()
        lite.close()
    with pytest.raises(SystemExit, match=message):
        rd.verified_plan(run_dir, sqlite_path)
