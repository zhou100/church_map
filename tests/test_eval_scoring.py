"""Unit tests for the website-extraction eval scorer.

Pure logic, no LLM calls — runnable in CI without any API keys.
"""
from __future__ import annotations

from evals.website_extraction.run import score_one, threshold_for


def test_deterministic_fields_keep_the_strict_band():
    for f in ("denomination", "theological_stance", "service_languages", "worship_style"):
        assert threshold_for(f, 0.10, 0.15) == 0.10


def test_judged_fields_get_the_wide_band():
    # Measured: vibe_tags moved 0.111 across two runs of the *same* prompt,
    # so a 0.10 band would fail prompt PRs on sampling alone.
    for f in ("vibe_tags", "programs", "community_summary", "pull_quote"):
        assert threshold_for(f, 0.10, 0.15) == 0.15


def test_unknown_field_defaults_to_strict():
    assert threshold_for("something_new", 0.10, 0.15) == 0.10


def test_denomination_substring_match():
    fields = {"denomination": "United Methodist Church"}
    assert score_one({"denomination": "United Methodist"}, fields)["denomination"] is True


def test_denomination_mismatch():
    fields = {"denomination": "Roman Catholic"}
    assert score_one({"denomination": "Southern Baptist"}, fields)["denomination"] is False


def test_denomination_null_extracted_fails():
    fields = {"denomination": None}
    assert score_one({"denomination": "Anything"}, fields)["denomination"] is False


def test_theological_stance_exact():
    assert score_one({"theological_stance": "progressive"}, {"theological_stance": "progressive"})["theological_stance"] is True
    assert score_one({"theological_stance": "progressive"}, {"theological_stance": "moderate"})["theological_stance"] is False


def test_service_languages_subset():
    fields = {"service_languages": ["English", "Spanish"]}
    assert score_one({"service_languages": ["English"]}, fields)["service_languages"] is True
    assert score_one({"service_languages": ["English", "Mandarin"]}, fields)["service_languages"] is False


def test_programs_must_include_any():
    fields = {"programs": ["AWANA Wednesdays", "Mens Bible Study"]}
    expected = {"programs_must_include_any": ["AWANA", "youth group"]}
    assert score_one(expected, fields)["programs"] is True

    fields_empty = {"programs": ["coffee hour"]}
    assert score_one(expected, fields_empty)["programs"] is False


def test_vibe_tags_must_include_any():
    fields = {"vibe_tags": ["affirming", "intergenerational"]}
    expected = {"vibe_tags_must_include_any": ["affirming"]}
    assert score_one(expected, fields)["vibe_tags"] is True


def test_worship_style_exact():
    assert score_one({"worship_style": "traditional-hymns"}, {"worship_style": "traditional-hymns"})["worship_style"] is True
    assert score_one({"worship_style": "traditional-hymns"}, {"worship_style": "contemporary"})["worship_style"] is False


def test_community_summary_substring():
    fields = {"community_summary": "An open and affirming Brooklyn congregation"}
    expected = {"community_summary_must_include_any": ["Brooklyn", "affirming"]}
    assert score_one(expected, fields)["community_summary"] is True


def test_pull_quote_substring():
    fields = {"pull_quote": "No matter where you are on your journey, you are welcome here"}
    expected = {"pull_quote_must_include_any": ["No matter where you are"]}
    assert score_one(expected, fields)["pull_quote"] is True


def test_statement_of_faith_min():
    fields = {"statement_of_faith": ["a", "b", "c", "d"]}
    assert score_one({"statement_of_faith_min": 3}, fields)["statement_of_faith"] is True
    assert score_one({"statement_of_faith_min": 5}, fields)["statement_of_faith"] is False


def test_statement_of_faith_min_handles_none():
    fields = {"statement_of_faith": None}
    assert score_one({"statement_of_faith_min": 1}, fields)["statement_of_faith"] is False


def test_only_specified_fields_scored():
    """Fields absent from `expected` should not appear in the score dict."""
    fields = {"denomination": "X", "theological_stance": "moderate", "vibe_tags": ["a"]}
    scores = score_one({"denomination": "X"}, fields)
    assert set(scores.keys()) == {"denomination"}


def test_normalize_case_insensitive():
    fields = {"vibe_tags": ["AFFIRMING"]}
    expected = {"vibe_tags_must_include_any": ["affirming"]}
    assert score_one(expected, fields)["vibe_tags"] is True
