"""Tests for the offline eval CI gate.

The gate's whole value is refusing to score a stale cache, so these cover
the refusal paths as well as the happy one. No LLM calls, no API keys.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.website_extraction import gate
from evals.website_extraction.run import GOLDEN, cache_meta, load_cache, prompt_fingerprint


def _golden_names() -> list[str]:
    return [json.loads(l)["name"] for l in GOLDEN.read_text().splitlines() if l.strip()]


# --- CURRENT pointer -------------------------------------------------------


def test_current_points_at_files_that_exist():
    stem = gate.read_current()
    assert (gate.BASELINE_DIR / f"{stem}.json").exists()
    assert (gate.BASELINE_DIR / f"{stem}.cache.json").exists()


def test_read_current_ignores_comments_and_blanks(tmp_path: Path):
    p = tmp_path / "CURRENT"
    p.write_text("# a comment\n\n2026-07-24.v3  # trailing\n")
    assert gate.read_current(p) == "2026-07-24.v3"


def test_read_current_rejects_empty(tmp_path: Path):
    p = tmp_path / "CURRENT"
    p.write_text("# nothing but comments\n")
    with pytest.raises(SystemExit):
        gate.read_current(p)


# --- freshness checks ------------------------------------------------------


def test_golden_jsonl_is_in_sync_with_markdown():
    assert gate.check_golden_in_sync() == []


def test_golden_out_of_sync_is_reported(tmp_path: Path):
    stale = tmp_path / "golden.jsonl"
    stale.write_text('{"name": "Example: nope", "input_text": "x", "expected": {}}\n')
    problems = gate.check_golden_in_sync(jsonl=stale)
    assert len(problems) == 1
    assert "compile" in problems[0]


def test_cache_covers_every_golden_example():
    stem = gate.read_current()
    cache = json.loads((gate.BASELINE_DIR / f"{stem}.cache.json").read_text())
    golden = [{"name": n} for n in _golden_names()]
    assert gate.check_cache_covers_golden(cache, golden) == []


def test_missing_cache_entry_is_reported():
    golden = [{"name": "Example: A"}, {"name": "Example: B"}]
    problems = gate.check_cache_covers_golden({"Example: A": {}}, golden)
    assert len(problems) == 1
    assert "Example: B" in problems[0]


def test_missing_cache_entries_are_truncated_in_the_message():
    golden = [{"name": f"Example: {i}"} for i in range(15)]
    problems = gate.check_cache_covers_golden({}, golden)
    assert "and 5 more" in problems[0]


def test_current_baseline_matches_the_current_prompt():
    stem = gate.read_current()
    baseline = json.loads((gate.BASELINE_DIR / f"{stem}.json").read_text())
    assert gate.check_prompt_fresh(baseline) == []


def test_current_cache_matches_the_current_prompt():
    stem = gate.read_current()
    meta = cache_meta(gate.BASELINE_DIR / f"{stem}.cache.json")
    assert meta["prompt_fingerprint"] == prompt_fingerprint()


def test_changed_prompt_is_reported():
    problems = gate.check_prompt_fresh({"prompt_fingerprint": "0000000000000000"})
    assert len(problems) == 1
    assert "prompt changed since the baseline" in problems[0]


def test_stale_cache_under_a_refreshed_baseline_is_reported():
    """The defeat move the cache stamp exists to block: re-saving a baseline
    from extractions that predate the prompt edit."""
    fresh_baseline = {"prompt_fingerprint": prompt_fingerprint()}
    stale_cache = {"prompt_fingerprint": "0000000000000000"}
    problems = gate.check_prompt_fresh(fresh_baseline, stale_cache)
    assert len(problems) == 1
    assert "prompt changed since the cache" in problems[0]


def test_unfingerprinted_baseline_and_cache_are_reported():
    problems = gate.check_prompt_fresh({"prompt_version": "2026-05-08.v3"}, {})
    assert len(problems) == 1
    assert "predate prompt fingerprinting" in problems[0]


def test_cache_meta_is_absent_from_loaded_examples():
    """`_meta` is bookkeeping — it must never be scored as an example."""
    stem = gate.read_current()
    cache = load_cache(gate.BASELINE_DIR / f"{stem}.cache.json")
    assert "_meta" not in cache
    assert set(cache) == set(_golden_names())


def test_fingerprint_is_stable_and_short():
    assert prompt_fingerprint() == prompt_fingerprint()
    assert len(prompt_fingerprint()) == 16


# --- end to end ------------------------------------------------------------


def test_gate_passes_against_its_own_baseline(capsys):
    assert gate.main([]) == 0
    assert "no LLM calls" in capsys.readouterr().out


def test_gate_fails_when_current_names_a_missing_baseline(capsys):
    assert gate.main(["--baseline-stem", "1999-01-01.v0"]) == 2
    assert "missing" in capsys.readouterr().err
