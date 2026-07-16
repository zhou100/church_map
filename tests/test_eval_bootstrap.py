"""Unit tests for the golden-set bootstrap: expected-building, disagreement
mining, markdown emission, and the compile round-trip. No network, no LLM.
"""
from __future__ import annotations

import datetime as dt

from evals.website_extraction.bootstrap import (
    _normalize_url,
    build_expected,
    existing_urls,
    find_disagreements,
    render_section,
)
from evals.website_extraction.compile import compile_md


REF_FIELDS = {
    "denomination": "Roman Catholic",
    "theological_stance": "traditional",
    "service_languages": ["English", "Spanish"],
    "worship_style": "liturgical",
    "programs": ["CCD", "RCIA"],
    "community_summary": "A bilingual parish.",
}


def test_build_expected_structured_only():
    expected = build_expected(REF_FIELDS)
    assert expected == {
        "denomination": "Roman Catholic",
        "theological_stance": "traditional",
        "service_languages": ["English", "Spanish"],
        "worship_style": "liturgical",
    }


def test_build_expected_drops_null_and_empty():
    expected = build_expected({"denomination": None, "service_languages": [], "worship_style": "blended"})
    assert expected == {"worship_style": "blended"}


def test_find_disagreements_agree():
    expected = build_expected(REF_FIELDS)
    flash = dict(REF_FIELDS)
    assert find_disagreements(expected, flash) == []


def test_find_disagreements_flags_field():
    expected = build_expected(REF_FIELDS)
    flash = dict(REF_FIELDS, theological_stance="moderate")
    out = find_disagreements(expected, flash)
    assert len(out) == 1
    assert out[0].startswith("theological_stance")


def test_render_section_names_by_agreement():
    kwargs = dict(
        name="St. Joseph",
        url="https://stjoseph.example.org",
        church_id=42,
        input_text="Mass in English and Spanish.",
        expected={"denomination": "Roman Catholic"},
        today=dt.date(2026, 7, 16),
    )
    trusted = render_section(**kwargs, disagreements=[])
    assert trusted.startswith("## Example: St. Joseph (auto)")
    assert "Agreement:" in trusted

    draft = render_section(**kwargs, disagreements=["denomination (production: null / reference: \"Roman Catholic\")"])
    assert draft.startswith("## DRAFT: St. Joseph (auto)")
    assert "Disagreements" in draft


def test_render_section_sanitizes_fences():
    section = render_section(
        name="Fence\nChurch",
        url="https://x.example.org",
        church_id=None,
        input_text="text with ``` fence",
        expected={},
        disagreements=[],
    )
    assert "## Example: Fence Church (auto)" in section
    assert "```text\ntext with ''' fence\n```" in section


def test_render_compile_round_trip(tmp_path):
    section = render_section(
        name="St. Joseph",
        url="https://stjoseph.example.org",
        church_id=42,
        input_text="Mass in English and Spanish with organ and cantor.",
        expected={"denomination": "Roman Catholic", "service_languages": ["English", "Spanish"]},
        disagreements=[],
    )
    md = tmp_path / "golden.md"
    out = tmp_path / "golden.jsonl"
    md.write_text("# Golden set\n\ndocs preamble\n\n---\n\n" + section)
    compile_md(md, out)

    import json
    records = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert len(records) == 1
    rec = records[0]
    assert rec["name"] == "Example: St. Joseph (auto)"
    assert rec["church_id"] == 42
    assert rec["url"] == "https://stjoseph.example.org"
    assert rec["input_text"] == "Mass in English and Spanish with organ and cantor."
    assert rec["expected"]["denomination"] == "Roman Catholic"


def test_existing_urls_ignores_synthetic():
    md = (
        "## Example: A\n- URL: synthetic\n- Church ID: null\n\n"
        "## Example: B\n- URL: https://b.example.org/\n- Church ID: 7\n"
    )
    assert existing_urls(md) == {"https://b.example.org"}


def test_normalize_url_adds_scheme():
    assert _normalize_url("example.org") == "https://example.org"
    assert _normalize_url("http://example.org") == "http://example.org"
    assert _normalize_url("  https://x.org ") == "https://x.org"
