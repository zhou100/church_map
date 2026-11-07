"""Programs stage checks that need no database: page text, verbatim excerpt
location, and the rules that drop or blank what the page does not state.

The model's answers here are written by hand to be wrong in the ways the plan
names (wrong campus, stale event, unsupported claim, invented ages, a college
group called youth); a real model is never called.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

from backend.scrapers_v2 import programs as mod
from backend.scrapers_v2.extract import ExtractionError, TransientExtractionError
from backend.scrapers_v2.programs import Page, check_programs, locate, page_text
from backend.scrapers_v2.r2 import R2Error, R2NotFound

KIDS_HTML = b"""<html><head><script>var nav = 'Nursery';</script><style>.k{}</style></head><body>
<nav><a href="/kids">Kids</a> <a href="/youth">Youth</a></nav>
<h2>Little Lambs Nursery</h2>
<p>Our nursery is open during both services for infants through age 3.</p>
<h2>Kids Church</h2>
<p>Kids Church for kindergarten through 5th grade meets during the 10:30 service.</p>
<h2>Kids Ministry</h2>
<p>Our Kids Ministry helps every child know Jesus and make friends.</p>
<h2>Youth Group</h2>
<p>Students in grades 6&#8211;12 meet Wednesdays at 7pm in the Youth Room.</p>
<h2>College &amp; Young Adults</h2>
<p>College students and young adults gather Thursdays at 7:30pm for dinner.</p>
<h2>VBS</h2>
<p>Vacation Bible School 2024 runs June 10-14 for ages 4 to 11.</p>
<h2>North Campus Kids</h2>
<p>At our Riverside campus, kids in grades 1-5 meet Sundays at 9am.</p>
<footer>Grace Church &middot; 123 Main St, Fresno CA &middot; Nursery available</footer>
</body></html>"""

PRESCHOOL_HTML = b"""<html><body>
<h1>Grace Early Learning Center</h1>
<p>Grace Preschool serves children ages 2-5, Monday through Friday, 7am-6pm. Now enrolling for fall.</p>
<p>Mother's Day Out for toddlers meets Tuesdays and Thursdays.</p>
</body></html>"""

WHEN = datetime(2026, 11, 3, 18, tzinfo=timezone.utc)
CHURCH = {"church_id": 7, "name": "Grace Church", "city": "Fresno", "address": "123 Main St"}


def _page(n: int, raw: bytes, kind: str = "kids") -> Page:
    return Page(artifact_id=100 + n, kind=kind, url=f"https://grace.example.org/{kind}",
                r2_key=f"raw_html/7/2026-11-03/{n}.html", content_hash=f"h{n}", fetched_at=WHEN,
                raw_sha256=hashlib.sha256(raw).hexdigest(), text=page_text(raw))


PAGES = [_page(1, KIDS_HTML), _page(2, PRESCHOOL_HTML, "childcare")]


def _one(item: dict, pages=PAGES):
    checked = check_programs({"programs": [item]}, pages, CHURCH)
    return (checked.programs[0] if checked.programs else None), checked.dropped


# ----- page text and excerpt location ------------------------------------------------

def test_page_text_keeps_footer_and_nav_but_not_scripts():
    text = page_text(KIDS_HTML)
    assert "Nursery available" in text            # footer
    assert "Kids Youth" in text or "Kids\nYouth" in text  # nav
    assert "var nav" not in text and ".k{}" not in text
    assert "grades 6-12" in text                    # en dash entity normalized


def test_locate_is_exact_unique_and_offsets_are_ours():
    text = PAGES[0].text
    quote = "Our nursery is open during both services for infants through age 3."
    start, end = locate(quote, text)
    assert text[start:end] == quote
    # Curly quotes, en dashes and spacing are normalized on both sides.
    assert locate("Students in grades 6–12  meet Wednesdays", text) != None
    # Case differs: still found once.
    assert locate("our NURSERY is open during both services", text) not in (None, "ambiguous")
    assert locate("Kids", text) == "ambiguous"
    assert locate("Our nursery is open on Saturdays", text) is None


# ----- what survives ------------------------------------------------------------------

def test_supported_program_keeps_bands_type_and_stated_fields():
    p, dropped = _one({"page": 1, "excerpt": "Our nursery is open during both services for infants through age 3.",
                       "name": "nursery", "type": "during_service", "age_bands": ["preschool"],
                       "ages_stated": "infants through age 3", "schedule_stated": "during both services"})
    assert dropped == {}
    assert p["program_type"] == "during_service"
    assert p["age_bands"] == ["preschool"]
    assert p["ages_stated"] == "infants through age 3"
    assert p["source_url"] == "https://grace.example.org/kids"
    assert PAGES[0].text[p["excerpt_start"]:p["excerpt_end"]] == p["excerpt"]
    assert p["raw_sha256"] == hashlib.sha256(KIDS_HTML).hexdigest()
    assert p["text_sha256"] == hashlib.sha256(PAGES[0].text.encode()).hexdigest()
    assert p["page_fetched_at"] == WHEN


def test_kids_without_ages_keeps_no_band():
    # The model guesses "children"; the page states no ages or grades.
    p, _ = _one({"page": 1, "excerpt": "Our Kids Ministry helps every child know Jesus and make friends.",
                 "name": "Kids Ministry", "type": "during_service", "age_bands": ["children", "preschool"]})
    assert p["age_bands"] == []
    assert p["program_type"] is None   # nothing says when it meets


def test_college_group_is_young_adult_never_youth():
    p, _ = _one({"page": 1, "excerpt": "College students and young adults gather Thursdays at 7:30pm for dinner.",
                 "name": "College students and young adults", "type": "other",
                 "age_bands": ["youth", "young_adult"], "schedule_stated": "Thursdays at 7:30pm"})
    assert p["age_bands"] == ["young_adult"]
    assert p["program_type"] == "other"


def test_explicit_grades_add_their_band_even_if_the_model_left_it_out():
    p, _ = _one({"page": 1, "excerpt": "Students in grades 6-12 meet Wednesdays at 7pm in the Youth Room.",
                 "name": "Students", "type": "other", "age_bands": [], "ages_stated": "grades 6-12"})
    assert p["age_bands"] == ["youth"]


def test_weekday_preschool_is_weekday_care_and_sunday_claims_are_dropped():
    p, _ = _one({"page": 2, "excerpt": "Grace Preschool serves children ages 2-5, Monday through Friday, 7am-6pm.",
                 "name": "Grace Preschool", "type": "weekday_care", "age_bands": ["preschool", "children"],
                 "ages_stated": "ages 2-5", "schedule_stated": "Monday through Friday, 7am-6pm"})
    assert p["program_type"] == "weekday_care"
    assert p["age_bands"] == ["preschool"]  # "ages 2-5" is before kindergarten: not a K-5 claim
    # The same preschool claimed as during-service care has no words for it.
    p, _ = _one({"page": 2, "excerpt": "Grace Preschool serves children ages 2-5, Monday through Friday, 7am-6pm.",
                 "name": "Grace Preschool", "type": "during_service", "age_bands": ["preschool"]})
    assert p["program_type"] is None


def test_unsupported_wrong_page_stale_and_other_campus_are_dropped():
    cases = [
        ({"page": 1, "excerpt": "Our nursery is open on Saturdays for infants and toddlers."}, "not_found"),
        ({"page": 2, "excerpt": "Our nursery is open during both services for infants through age 3."}, "not_found"),
        ({"page": 9, "excerpt": "Our nursery is open during both services for infants through age 3."}, "bad_page"),
        ({"page": 1, "excerpt": "Kids"}, "too_short"),
        ({"page": 1, "excerpt": "Vacation Bible School 2024 runs June 10-14 for ages 4 to 11."}, "stale"),
        ({"page": 1, "excerpt": "At our Riverside campus, kids in grades 1-5 meet Sundays at 9am.",
          "campus_stated": "Riverside campus"}, "other_campus"),
        ({"page": 1, "excerpt": "Grace Church · 123 Main St, Fresno CA · Nursery available"}, None),
    ]
    for item, reason in cases:
        p, dropped = _one(item)
        if reason is None:
            assert p is not None and dropped == {}, item
        else:
            assert p is None and dropped == {reason: 1}, (item, dropped)


def test_stated_fields_outside_the_excerpt_are_blanked():
    p, _ = _one({"page": 1, "excerpt": "Our nursery is open during both services for infants through age 3.",
                 "name": "Little Lambs Nursery", "ages_stated": "0-36 months", "schedule_stated": "Sundays 9am"})
    assert (p["name_stated"], p["ages_stated"], p["schedule_stated"]) == (None, None, None)
    assert p["age_bands"] == []  # no proposed band, and "0-36 months" is not on the page


def test_adult_only_and_malformed_answers_are_dropped():
    checked = check_programs({"programs": [
        {"page": 1, "excerpt": "Our nursery is open during both services for infants through age 3.", "type": "bogus",
         "age_bands": "preschool"},
        "not a dict",
    ]}, PAGES, CHURCH)
    assert len(checked.programs) == 1
    assert checked.programs[0]["program_type"] is None and checked.programs[0]["age_bands"] == []
    assert checked.dropped == {"bad_shape": 1}
    assert check_programs({"programs": "none"}, PAGES, CHURCH).dropped == {"bad_shape": 1}
    assert check_programs({"programs": []}, PAGES, CHURCH).programs == []
    text = page_text(b"<p>Women's Bible Study meets Tuesdays at 10am in the fellowship hall.</p>")
    adult = Page(1, "homepage", "https://grace.example.org/", "k", None, WHEN, "x", text)
    checked = check_programs({"programs": [{"page": 1, "excerpt": "Women's Bible Study meets Tuesdays at 10am"}]},
                             [adult], CHURCH)
    assert checked.programs == [] and checked.dropped == {"not_kids": 1}


def test_repeated_program_is_kept_once():
    item = {"page": 1, "excerpt": "Our nursery is open during both services for infants through age 3.",
            "name": "nursery", "type": "during_service", "age_bands": ["preschool"]}
    checked = check_programs({"programs": [item, dict(item)]}, PAGES, CHURCH)
    assert len(checked.programs) == 1 and checked.dropped == {"duplicate": 1}


# ----- one church end to end, with fakes -------------------------------------------

class _R2:
    def __init__(self, objects, fail=()):
        self.objects, self.fail, self.reads = objects, set(fail), 0

    def get_html(self, key):
        self.reads += 1
        if key in self.fail:
            raise R2Error("throttled")
        if key not in self.objects:
            raise R2NotFound(key)
        return self.objects[key]


class _Repo:
    def __init__(self):
        self.records = []

    async def record_program_extraction(self, church_id, input_ids, **kw):
        self.records.append({"church_id": church_id, "input_ids": input_ids, **kw})


def _target(**objects):
    keys = list(objects)
    return {**CHURCH, "artifact_ids": [11, 10][: len(keys)], "kinds": ["kids", "homepage"][: len(keys)],
            "urls": [f"https://grace.example.org/{k}" for k in keys], "r2_keys": keys,
            "content_hashes": [None] * len(keys), "fetched_ats": [WHEN] * len(keys)}


def _run(target, r2, call):
    repo = _Repo()
    outcome = asyncio.run(mod.extract_programs_for_church(repo, r2, target, call=call))
    return outcome, repo.records


def test_pages_without_program_words_cost_no_model_call():
    calls = []

    async def call(*a, **k):
        calls.append(1)
        return {"programs": []}

    plain = b"<p>Sunday worship at 10am. All are welcome. Parking behind the building.</p>"
    outcome, records = _run(_target(home=plain), _R2({"home": plain}), call)
    assert outcome == "no_program_text" and calls == []
    assert records[0]["status"] == "no_program_text" and records[0]["programs"] == []


def test_model_answer_is_checked_and_recorded_with_sorted_inputs():
    seen = {}

    async def call(text, **kw):
        seen.update(text=text, **kw)
        return {"programs": [
            {"page": 1, "excerpt": "Our nursery is open during both services for infants through age 3.",
             "type": "during_service", "age_bands": ["preschool"]},
            {"page": 1, "excerpt": "This sentence is not on the page about kids at all."},
        ]}

    outcome, records = _run(_target(kids=KIDS_HTML, home=b"<p>Welcome</p>"),
                            _R2({"kids": KIDS_HTML, "home": b"<p>Welcome</p>"}), call)
    assert outcome == "ok"
    assert seen["model"] == mod.MODEL and seen["system_prompt"] == mod.SYSTEM_PROMPT
    assert seen["text"].startswith("=== PAGE 1 (kids) https://grace.example.org/kids ===")
    assert "Welcome" not in seen["text"]  # a page without program words is not sent
    rec = records[0]
    assert rec["input_ids"] == [10, 11] and rec["status"] == "ok"
    assert len(rec["programs"]) == 1 and rec["dropped"] == {"not_found": 1}
    assert rec["extractor_version"] == mod.PROMPT_VERSION


def test_transient_failures_write_nothing_and_bad_answers_keep_old_programs():
    async def transient(*a, **k):
        raise TransientExtractionError("upstream-503")

    async def junk(*a, **k):
        raise ExtractionError("no JSON object")

    target, objects = _target(kids=KIDS_HTML), {"kids": KIDS_HTML}
    assert _run(target, _R2(objects), transient) == ("transient", [])
    assert _run(target, _R2(objects, fail={"kids"}), junk) == ("transient", [])
    outcome, records = _run(target, _R2(objects), junk)
    assert outcome == "error" and records[0]["programs"] is None


# ----- review of PR 81: campus identity, missing archives, malformed answers --------

SOUTH = "Grace Church South Campus offers kids in grades 1-5 a Sunday program."


def _campus_case(church, excerpt, campus=None):
    html = f"<html><body><p>{excerpt}</p></body></html>".encode()
    item = {"page": 1, "excerpt": excerpt, "type": "during_service", "age_bands": ["children"]}
    if campus:
        item["campus_stated"] = campus
    checked = check_programs({"programs": [item]}, [_page(1, html)], church)
    return checked.programs, checked.dropped


def test_shared_church_name_does_not_make_another_campus_ours():
    north = {**CHURCH, "name": "Grace Church North Campus"}
    south = {**CHURCH, "name": "Grace Church South Campus"}
    # Model named the campus, and when it left campus_stated empty: both dropped.
    assert _campus_case(north, SOUTH, "Grace Church South Campus") == ([], {"other_campus": 1})
    assert _campus_case(north, SOUTH) == ([], {"other_campus": 1})
    # The campus it is about keeps it.
    kept, dropped = _campus_case(south, SOUTH, "Grace Church South Campus")
    assert dropped == {} and kept[0]["campus_stated"] == "Grace Church South Campus"
    assert _campus_case(south, SOUTH)[1] == {}
    # A campus we cannot tie to this record is not kept either.
    assert _campus_case(CHURCH, "Our North Campus has a nursery for infants and toddlers on Sundays.")[1] \
        == {"other_campus": 1}
    # Named by this church's city: ours.
    assert _campus_case(CHURCH, "The Fresno Campus has a nursery for infants and toddlers on Sundays.")[1] == {}


def test_a_missing_archived_page_keeps_old_programs_and_costs_no_call():
    calls = []

    async def call(*a, **k):
        calls.append(1)
        return {"programs": []}

    # The only page is gone, and one of two pages is gone: neither is "no programs".
    for objects, keys in [({}, {"kids": KIDS_HTML}), ({"home": b"<p>Welcome</p>"},
                                                     {"kids": KIDS_HTML, "home": b"<p>Welcome</p>"})]:
        outcome, records = _run(_target(**keys), _R2(objects), call)
        assert outcome == "missing_archive" and calls == []
        assert records[0]["status"] == "error" and records[0]["programs"] is None
        assert records[0]["input_ids"] == []  # never the due set, so it is retried
        assert "missing" in records[0]["error_detail"]


def test_an_answer_of_the_wrong_shape_keeps_old_programs():
    for answer in [{"programs": "none"}, {}, {"result": []}, ["programs"], None]:
        async def call(*a, answer=answer, **k):
            return answer

        outcome, records = _run(_target(kids=KIDS_HTML), _R2({"kids": KIDS_HTML}), call)
        assert outcome == "error" and records[0]["programs"] is None, answer
        assert records[0]["status"] == "error" and records[0]["input_ids"] == [11]

    async def none_found(*a, **k):
        return {"programs": []}

    outcome, records = _run(_target(kids=KIDS_HTML), _R2({"kids": KIDS_HTML}), none_found)
    assert outcome == "ok" and records[0]["programs"] == []  # a well-formed "none" does clear


def test_dry_run_counts_missing_archives_apart():
    class Repo:
        async def due_for_program_extraction(self, limit):
            return [{**_target(kids=KIDS_HTML), "church_id": 1}, {**_target(gone=KIDS_HTML), "church_id": 2}]

    counts = asyncio.run(mod.run_program_batch(Repo(), _R2({"kids": KIDS_HTML}), limit=5, apply=False))
    assert (counts["would_call_model"], counts["missing_archive"], counts["no_program_text"]) == (1, 1, 0)
