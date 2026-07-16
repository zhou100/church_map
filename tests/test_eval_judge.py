"""Unit tests for the LLM-judge plumbing: verdict parsing, score merging,
cache format upgrade. Pure logic, no LLM calls — runnable in CI without keys.
"""
from __future__ import annotations

import json

from evals.website_extraction.judge import (
    JUDGE_FIELDS,
    build_judge_input,
    parse_verdicts,
    verbatim_pull_quote_ok,
)
from evals.website_extraction.run import load_cache, merge_judge_scores


def test_parse_verdicts_valid():
    raw = {f: {"ok": True, "reason": "fine"} for f in JUDGE_FIELDS}
    verdicts = parse_verdicts(raw)
    assert set(verdicts.keys()) == set(JUDGE_FIELDS)
    assert all(v["ok"] is True for v in verdicts.values())


def test_parse_verdicts_drops_malformed():
    raw = {
        "programs": {"ok": True, "reason": "x"},
        "vibe_tags": {"ok": "yes"},          # non-bool ok
        "community_summary": "looks good",   # not a dict
        "unknown_field": {"ok": True},       # not a judged field
    }
    verdicts = parse_verdicts(raw)
    assert set(verdicts.keys()) == {"programs"}


def test_parse_verdicts_non_dict_input():
    assert parse_verdicts(None) == {}
    assert parse_verdicts([1, 2]) == {}


def test_parse_verdicts_missing_reason_ok():
    verdicts = parse_verdicts({"programs": {"ok": False}})
    assert verdicts["programs"] == {"ok": False, "reason": ""}


def test_verbatim_pull_quote_whitespace_and_case():
    text = "We are a family of faith.\nAll   are welcome here."
    assert verbatim_pull_quote_ok("all are welcome here.", text) is True
    assert verbatim_pull_quote_ok("We are a family of faith.", text) is True
    assert verbatim_pull_quote_ok("A quote that is not there", text) is False


def test_verbatim_pull_quote_empty_passes():
    assert verbatim_pull_quote_ok("", "anything") is True
    assert verbatim_pull_quote_ok(None, "anything") is True


def test_build_judge_input_contains_text_and_extraction():
    body = build_judge_input("SOURCE TEXT", {"programs": ["youth"], "denomination": "PCA"})
    assert body.startswith("SOURCE TEXT")
    assert '"programs"' in body
    # Non-judged fields stay out of the judge's view.
    assert "PCA" not in body


def test_merge_judge_fills_unscored_fields():
    det = {"denomination": True}
    verdicts = {"programs": {"ok": True, "reason": ""}, "vibe_tags": {"ok": False, "reason": ""}}
    merged = merge_judge_scores(det, verdicts, {}, "text")
    assert merged == {"denomination": True, "programs": True, "vibe_tags": False}


def test_merge_deterministic_wins_over_judge():
    """Hand-written canaries keep their *_must_include_any scores."""
    det = {"programs": True}
    verdicts = {"programs": {"ok": False, "reason": "judge disagrees"}}
    merged = merge_judge_scores(det, verdicts, {}, "text")
    assert merged["programs"] is True


def test_merge_pull_quote_requires_verbatim():
    text = "Come as you are."
    fields = {"pull_quote": "A fabricated quote"}
    verdicts = {"pull_quote": {"ok": True, "reason": "sounds right"}}
    merged = merge_judge_scores({}, verdicts, fields, text)
    assert merged["pull_quote"] is False

    fields_ok = {"pull_quote": "Come as you are."}
    merged_ok = merge_judge_scores({}, verdicts, fields_ok, text)
    assert merged_ok["pull_quote"] is True


def test_load_cache_upgrades_v1(tmp_path):
    v1 = {"Example: X": {"fields": {"denomination": "PCA"}, "confidence": {}, "snippets": {}}}
    p = tmp_path / "cache.json"
    p.write_text(json.dumps(v1))
    cache = load_cache(p)
    assert cache["Example: X"]["extraction"]["fields"]["denomination"] == "PCA"
    assert cache["Example: X"]["judge"] is None


def test_load_cache_passes_v2_through(tmp_path):
    v2 = {
        "Example: X": {
            "extraction": {"fields": {}, "confidence": {}, "snippets": {}},
            "judge": {"programs": {"ok": True, "reason": ""}},
        }
    }
    p = tmp_path / "cache.json"
    p.write_text(json.dumps(v2))
    cache = load_cache(p)
    assert cache["Example: X"]["judge"]["programs"]["ok"] is True
