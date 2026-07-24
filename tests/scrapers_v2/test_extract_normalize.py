"""Normalization + schema validation for the v3 extraction prompt."""
import asyncio

import httpx
import pytest

from backend.scrapers_v2 import extract as extract_mod
from backend.scrapers_v2.extract import (
    ExtractionError,
    TransientExtractionError,
    _parse_json_object,
    call_llm,
    normalize_extraction,
)


def test_error_classes_distinct():
    # Transient and terminal must be different exception classes so the
    # extract loop can route them correctly: transient leaves artifacts
    # pending for retry, terminal marks them error.
    assert not issubclass(TransientExtractionError, ExtractionError)
    assert not issubclass(ExtractionError, TransientExtractionError)


SOURCE = (
    "Welcome to First Baptist. We are a Southern Baptist congregation in "
    "downtown Denver. Sunday services blend hymns and contemporary worship. "
    "We believe Scripture is the inspired word of God."
)


def _call_llm_against(handler, **kw):
    """Drive call_llm over a mocked transport.

    asyncio.run rather than pytest-asyncio: the suite has no async plugin,
    and an async test without one is silently *skipped*, which is worse than
    not having it. Retry sleeps are patched out so this stays instant.
    """
    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await call_llm("text", api_key="k", client=client, **kw)
        finally:
            await client.aclose()

    return asyncio.run(go())


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(extract_mod.asyncio, "sleep", instant)


@pytest.mark.parametrize("content", [None, "", "   "])
def test_call_llm_retries_empty_content(content):
    """A 200 carrying null/empty content is a blip, not a crash.

    Seen live: the judge model returned "content": null and the run died on
    None.strip(), losing every completed extraction with it.
    """
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": 1}'}}]})

    assert _call_llm_against(handler) == {"ok": 1}
    assert calls["n"] == 2


def test_call_llm_gives_up_on_persistent_empty_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    with pytest.raises(TransientExtractionError, match="empty-content"):
        _call_llm_against(handler)


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
