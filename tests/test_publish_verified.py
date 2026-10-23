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
