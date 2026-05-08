"""Normalization + schema validation for the v3 extraction prompt."""
from backend.scrapers_v2.extract import _parse_json_object, normalize_extraction


SOURCE = (
    "Welcome to First Baptist. We are a Southern Baptist congregation in "
    "downtown Denver. Sunday services blend hymns and contemporary worship. "
    "We believe Scripture is the inspired word of God."
)


def test_parse_json_object_strips_codefence():
    out = _parse_json_object('```json\n{"a": 1}\n```')
    assert out == {"a": 1}


def test_parse_json_object_raw():
    assert _parse_json_object('{"a": 1}') == {"a": 1}


def test_normalize_drops_invalid_enum():
    raw = {
        "denomination": "Southern Baptist",
        "theological_stance": "fundamentalist",  # not in enum
        "worship_style": "rock-concert",         # not in enum
        "service_languages": ["English"],
        "programs": [],
        "vibe_tags": [],
        "community_summary": "",
        "theology_summary": "",
        "worship_style_detail": "",
        "pull_quote": "",
        "statement_of_faith": [],
    }
    out = normalize_extraction(raw, SOURCE)
    assert out["fields"]["theological_stance"] is None
    assert out["fields"]["worship_style"] is None
    assert out["fields"]["denomination"] == "Southern Baptist"


def test_normalize_drops_non_substring_snippets():
    raw = {
        "denomination": "Baptist",
        "theological_stance": None,
        "service_languages": [],
        "programs": [],
        "vibe_tags": [],
        "community_summary": "",
        "theology_summary": "",
        "worship_style": None,
        "worship_style_detail": "",
        "pull_quote": "",
        "statement_of_faith": [],
        "_source_snippets": {
            "denomination": "Southern Baptist congregation",  # in source
            "vibe_tags": "we are robots from outer space",     # NOT in source — should drop
        },
        "_confidence": {"denomination": 0.9, "vibe_tags": 0.5},
    }
    out = normalize_extraction(raw, SOURCE)
    assert "denomination" in out["snippets"]
    assert "vibe_tags" not in out["snippets"]
    # Confidence is independent of snippet validation.
    assert out["confidence"]["denomination"] == 0.9


def test_normalize_clamps_confidence_range():
    raw = {
        "denomination": None, "theological_stance": None, "service_languages": [],
        "programs": [], "vibe_tags": [], "community_summary": "",
        "theology_summary": "", "worship_style": None, "worship_style_detail": "",
        "pull_quote": "", "statement_of_faith": [],
        "_confidence": {
            "x": 1.5,    # out of range, drop
            "y": -0.1,   # out of range, drop
            "z": 0.7,    # ok
            "w": "high", # not a number, drop
        },
    }
    out = normalize_extraction(raw, SOURCE)
    assert out["confidence"] == {"z": 0.7}


def test_normalize_handles_missing_optional_fields():
    raw = {}  # nothing
    out = normalize_extraction(raw, SOURCE)
    assert out["fields"]["denomination"] is None
    assert out["fields"]["service_languages"] == []
    assert out["confidence"] == {}
    assert out["snippets"] == {}


def test_normalize_caps_statement_of_faith_at_eight():
    raw = {
        "denomination": None, "theological_stance": None, "service_languages": [],
        "programs": [], "vibe_tags": [], "community_summary": "",
        "theology_summary": "", "worship_style": None, "worship_style_detail": "",
        "pull_quote": "",
        "statement_of_faith": [f"belief {i}" for i in range(20)],
    }
    out = normalize_extraction(raw, SOURCE)
    assert len(out["fields"]["statement_of_faith"]) == 8
