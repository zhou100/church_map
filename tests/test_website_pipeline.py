"""Tests for the website pipeline: env loader, fetcher cache, extractor, embedder."""
from __future__ import annotations

import json
import sqlite3
import struct
from unittest.mock import patch

import httpx
import pytest

from backend import env_loader
from backend.scrapers import migrate_website_pipeline, website_embed, website_extract, website_fetch


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE Churches (
            church_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, website TEXT, denomination TEXT
        );
        """
    )
    con.commit()
    con.close()
    migrate_website_pipeline.migrate(str(path))
    con = sqlite3.connect(path)
    con.execute("INSERT INTO Churches (name, website) VALUES (?, ?)", ("Test Church", "https://example.com"))
    con.commit()
    yield con
    con.close()


def test_env_loader_normalizes_lowercase_keys(tmp_path, monkeypatch):
    f = tmp_path / "env.local"
    f.write_text("open_router_key=sk-or-abc\nvoyage_api_key=pa-xyz\n")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    n = env_loader.load_env_local(f)
    assert n == 2
    import os
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-abc"
    assert os.environ["VOYAGE_API_KEY"] == "pa-xyz"


def test_env_loader_does_not_override_existing(tmp_path, monkeypatch):
    f = tmp_path / "env.local"
    f.write_text("open_router_key=from-file\n")
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-shell")
    env_loader.load_env_local(f)
    import os
    assert os.environ["OPENROUTER_API_KEY"] == "from-shell"


def test_normalize_url():
    assert website_fetch._normalize_url("example.com") == "https://example.com/"
    assert website_fetch._normalize_url("https://x.com/path?a=1") == "https://x.com/path"
    assert website_fetch._normalize_url("") is None
    assert website_fetch._normalize_url("not a url") is None


def test_candidate_links_picks_known_kinds():
    html = """
    <a href='/about'>About</a>
    <a href='/what-we-believe'>Beliefs</a>
    <a href='https://other.com/about'>External</a>
    <a href='/blog/post-1'>Blog</a>
    """
    links = website_fetch._candidate_links(html, "https://example.com/")
    assert links.get("about") == "https://example.com/about"
    assert links.get("beliefs") == "https://example.com/what-we-believe"
    assert "blog" not in links


def test_extract_parse_json_object_handles_fenced():
    obj = website_extract._parse_json_object('```json\n{"a":1,"b":[2]}\n```')
    assert obj == {"a": 1, "b": [2]}


def test_extract_parse_json_raises_when_missing():
    with pytest.raises(website_extract.ExtractionError):
        website_extract._parse_json_object("no json here")


def test_extract_normalize_clamps_stance_and_lists():
    norm = website_extract._normalize({
        "denomination": "  Baptist  ",
        "theological_stance": "fundamentalist",   # not a valid bucket → null
        "service_languages": ["English", "", "Spanish"],
        "programs": "not a list",
        "vibe_tags": ["family", " ", "warm"],
        "summary": "  hi  ",
    })
    assert norm["denomination"] == "Baptist"
    assert norm["theological_stance"] is None
    assert norm["service_languages"] == ["English", "Spanish"]
    assert norm["programs"] == []
    assert norm["vibe_tags"] == ["family", "warm"]
    assert norm["summary"] == "hi"


def test_extract_persist_writes_columns(db):
    cid = 1
    norm = {
        "denomination": "Anglican",
        "theological_stance": "moderate",
        "service_languages": ["English"],
        "programs": ["youth group"],
        "vibe_tags": ["liturgical"],
        "summary": "A liturgical Anglican parish.",
    }
    website_extract._persist(db, cid, norm)
    row = db.execute(
        "SELECT website_summary, extracted_tags, extracted_status, denomination, extracted_prompt_version FROM Churches WHERE church_id=?",
        (cid,),
    ).fetchone()
    assert row[0] == "A liturgical Anglican parish."
    tags = json.loads(row[1])
    assert tags["theological_stance"] == "moderate"
    assert tags["vibe_tags"] == ["liturgical"]
    assert row[2] == "ok"
    assert row[3] == "Anglican"
    assert row[4] == website_extract.PROMPT_VERSION


def test_extract_call_llm_routes_to_openrouter():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"denomination":"X","theological_stance":null,"service_languages":[],"programs":[],"vibe_tags":[],"summary":"s"}'}}]
        })

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        out = website_extract.call_llm("hello", api_key="test-key", client=client)
    assert out["denomination"] == "X"
    assert "openrouter.ai" in captured["url"]
    assert captured["headers"]["authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == website_extract.MODEL


def test_extract_call_llm_raises_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(website_extract.ExtractionError):
        website_extract.call_llm("hi")


def test_embed_pack_unpack_roundtrip():
    vec = [0.0, 1.0, -1.5] + [0.1] * (website_embed.DIM - 3)
    blob = website_embed._pack(vec)
    assert len(blob) == website_embed.DIM * 4
    out = website_embed.unpack(blob)
    assert len(out) == website_embed.DIM
    assert out[0] == 0.0 and abs(out[2] - -1.5) < 1e-6


def test_embed_source_text_for_assembles_fields(db):
    db.execute("UPDATE Churches SET denomination='Baptist', website_summary='Welcoming.', extracted_tags=? WHERE church_id=1",
               (json.dumps({"vibe_tags": ["warm"], "service_languages": ["English"]}),))
    txt = website_embed.source_text_for(db, 1)
    assert txt is not None
    assert "Baptist" in txt and "Welcoming" in txt and "warm" in txt and "English" in txt


def test_embed_source_text_returns_none_without_summary_or_tags(db):
    txt = website_embed.source_text_for(db, 1)
    assert txt is None


def test_embed_batch_calls_voyage():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        n = len(captured["body"]["input"])
        fake_vec = [0.01] * website_embed.DIM
        return httpx.Response(200, json={"data": [{"embedding": fake_vec} for _ in range(n)]})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        vecs = website_embed.embed_batch(["a", "b"], api_key="test", client=client)
    assert len(vecs) == 2
    assert len(vecs[0]) == website_embed.DIM
    assert "voyageai" in captured["url"]
    assert captured["body"]["model"] == website_embed.MODEL


def test_fetch_upsert_page_dedups(db):
    fr = website_fetch.FetchResult(url="https://example.com/", kind="homepage", status_code=200, text="hi", error=None)
    website_fetch._upsert_page(db, 1, "homepage", fr, robots_allowed=True)
    website_fetch._upsert_page(db, 1, "homepage", fr, robots_allowed=True)
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM website_pages WHERE church_id=1").fetchone()[0]
    assert n == 1
