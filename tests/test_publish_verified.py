"""scripts/publish_verified.py write rules (no database)."""
from scripts.publish_verified import plan_fields, summarize

FIELDS = ["address", "phone", "website", "latitude", "kids_program"]


def test_fill_blanks_and_replace_differences_only():
    current = {"address": "", "phone": "(650) 555-0100", "website": "https://old.example.org", "latitude": 37.5}
    desired = {"address": "100 Main St", "phone": "(650)  555-0100", "website": "https://grace.example.org",
               "latitude": 37.5000001, "kids_program": "Sunday school"}
    plan = {f: (a, o, n) for f, a, o, n in plan_fields(current, desired, FIELDS)}
    assert plan["address"][0] == "fill" and plan["kids_program"][0] == "fill"
    assert plan["website"] == ("replace", "https://old.example.org", "https://grace.example.org")
    assert "phone" not in plan  # same value, spacing aside
    assert "latitude" not in plan  # same point within 1e-6


def test_never_blanks_a_field():
    assert plan_fields({"phone": "(650) 555-0100"}, {"phone": None}, ["phone"]) == []
    assert plan_fields({"phone": "(650) 555-0100"}, {"phone": "  "}, ["phone"]) == []


def test_never_writes_facebook_into_website():
    assert plan_fields({}, {"website": "https://www.facebook.com/grace"}, ["website"]) == []


def test_a_new_congregation_fills_every_field():
    plan = plan_fields(None, {"address": "1 A St", "phone": "x"}, ["address", "phone"])
    assert [(f, a) for f, a, _, _ in plan] == [("address", "fill"), ("phone", "fill")]


def test_summary_counts_by_kind_field_and_action():
    plan = [{"kind": "insert", "changes": [("name", "fill", None, "Grace")]},
            {"kind": "update", "changes": [("phone", "replace", "1", "2"), ("address", "fill", None, "x")]}]
    text = summarize(plan)
    assert "churches to update: 1; new congregations to insert: 1" in text
    assert "update phone" in " ".join(text.split()) and "replace 1" in " ".join(text.split())


def test_formatting_only_differences_are_not_rewritten():
    current = {"phone": "+1-510-339-2200", "website": "https://redemptionsf.com", "facebook_url": "http://facebook.com/grace"}
    desired = {"phone": "(510) 339-2200", "website": "https://www.redemptionsf.com/", "facebook_url": "https://www.facebook.com/grace/"}
    assert plan_fields(current, desired, ["phone", "website", "facebook_url"]) == []
    changed = plan_fields({"phone": "(510) 451-9608"}, {"phone": "(415) 346-6466"}, ["phone"])
    assert [(f, a) for f, a, _, _ in changed] == [("phone", "replace")]


def test_private_diff_directory(tmp_path, monkeypatch):
    from scripts import publish_verified as publisher
    monkeypatch.setattr(publisher, 'EXPORTS', tmp_path / 'state')
    plan = [{'kind': 'update', 'subject': '1', 'church_id': 1,
             'changes': [('phone', 'fill', None, 'PRIVATE')]}]
    path = publisher.write_diff(plan, 'fixture', tmp_path / 'private')
    assert 'PRIVATE' in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert not publisher.EXPORTS.exists()


def test_schema_same_name_view_cannot_mask_missing_column():
    import os
    import pytest
    import psycopg
    from scripts.publish_verified import check_schema
    if not os.environ.get('DATABASE_URL'):
        pytest.skip('isolated Postgres DATABASE_URL required')
    with psycopg.connect(os.environ['DATABASE_URL']) as con:
        # Transactional fixture; no destructive migration or existing view changes.
        con.execute('CREATE SCHEMA publisher_schema_fixture')
        con.execute('CREATE VIEW publisher_schema_fixture.churches AS SELECT kids_program FROM public.churches')
        con.execute('ALTER TABLE public.churches RENAME COLUMN kids_program TO fixture_missing_kids')
        # View output retains kids_program, precisely reproducing the old false pass.
        assert con.execute("SELECT column_name FROM information_schema.columns WHERE table_name='churches' AND column_name='kids_program'").fetchone()
        with pytest.raises(SystemExit, match='kids_program'):
            check_schema(con)
        con.rollback()


def test_rls_that_hides_rows_stops_the_plan():
    """Production enables RLS on churches and publish_log. A role without a matching
    SELECT policy reads zero rows silently, so build_plan would re-insert every
    published congregation, and a hidden revert would let the gate pass a run it
    must hold. Review of #84: a hidden log cannot be caught by counting the log."""
    import os
    import pytest
    import psycopg
    from scripts.publish_verified import check_visibility
    if not os.environ.get('DATABASE_URL'):
        pytest.skip('isolated Postgres DATABASE_URL required')
    with psycopg.connect(os.environ['DATABASE_URL']) as con:
        # One transaction, rolled back: role, RLS flags, policies and rows all vanish.
        con.execute("INSERT INTO churches (name, source) VALUES ('Directory fixture', 'osm')")
        muse = con.execute("INSERT INTO churches (name, source, external_id) VALUES ('Muse fixture', 'muse', "
                           "'rls-fixture') RETURNING church_id").fetchone()[0]
        con.execute("INSERT INTO publish_log (run_id, church_id, field, action) VALUES "
                    "('rls-fixture', %s, '*', 'insert')", (muse,))
        con.execute('CREATE ROLE rls_fixture_reader NOLOGIN')
        con.execute('GRANT SELECT ON churches, publish_log TO rls_fixture_reader')
        con.execute('ALTER TABLE churches ENABLE ROW LEVEL SECURITY')
        con.execute('ALTER TABLE publish_log ENABLE ROW LEVEL SECURITY')

        def check_as_reader():
            con.execute('SET LOCAL ROLE rls_fixture_reader')
            try:
                check_visibility(con)
            finally:
                con.execute('RESET ROLE')

        def policy(sql):
            con.execute(sql.replace('ROLE', 'rls_fixture_reader'))

        # No policy at all: every read is empty.
        with pytest.raises(SystemExit, match='churches'):
            check_as_reader()
        # Directory visible, published rows hidden.
        policy("CREATE POLICY dir ON churches FOR SELECT TO ROLE USING (source IS DISTINCT FROM 'muse')")
        policy('CREATE POLICY log ON publish_log FOR SELECT TO ROLE USING (true)')
        with pytest.raises(SystemExit, match='churches'):
            check_as_reader()
        # Churches complete, but the log (with its inserts and reverts) hidden.
        policy('CREATE POLICY everything ON churches FOR SELECT TO ROLE USING (true)')
        con.execute('DROP POLICY log ON publish_log')
        with pytest.raises(SystemExit, match='publish_log'):
            check_as_reader()
        policy('CREATE POLICY log ON publish_log FOR SELECT TO ROLE USING (true)')
        check_as_reader()
        # A restrictive policy can hide rows a permissive USING (true) admits.
        policy("CREATE POLICY narrow ON publish_log AS RESTRICTIVE FOR SELECT TO ROLE USING (action <> 'revert')")
        with pytest.raises(SystemExit, match='publish_log'):
            check_as_reader()
        con.rollback()
