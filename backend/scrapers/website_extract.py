"""LLM extraction over cached website pages.

Reads concatenated text for a church from website_pages and asks
google/gemini-2.5-flash via OpenRouter for a structured JSON object:

    {
      "denomination": str | null,
      "theological_stance": "traditional" | "moderate" | "progressive" | null,
      "service_languages": [str],
      "programs": [str],
      "vibe_tags": [str],
      "community_summary": str,         # 1-2 sentences on who they are
      "theology_summary": str,          # 1-2 sentences on what they teach
      "worship_style": "liturgical" | "traditional-hymns" | "blended" |
                       "contemporary" | "charismatic" | null,
      "worship_style_detail": str,      # 1 short sentence with specifics
      "pull_quote": str,                # verbatim quote from source, <=200 chars
      "statement_of_faith": [str]       # 3-8 doctrinal bullets, only if site lists them
    }

community_summary stays in the Churches.website_summary column (it's the
lead text rendered in the panel). All other fields ride along inside the
extracted_tags JSON object — flexible schema, no migration required when
fields are added or removed.

Bump PROMPT_VERSION whenever the prompt or schema changes so the eval
harness can baseline against prior versions.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

PROMPT_VERSION = "2026-05-07.v2"

WORSHIP_STYLES = {"liturgical", "traditional-hymns", "blended", "contemporary", "charismatic"}
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-2.5-flash"
MAX_INPUT_CHARS = 18_000   # truncate concatenated text — Flash handles it cheaply but we cap for cost predictability
HTTP_TIMEOUT_S = 60.0


SYSTEM_PROMPT = """You are extracting structured facts about a Christian church from its public website text.

Return STRICT JSON matching this schema (no prose, no markdown):
{
  "denomination": string | null,
  "theological_stance": "traditional" | "moderate" | "progressive" | null,
  "service_languages": string[],
  "programs": string[],
  "vibe_tags": string[],
  "community_summary": string,
  "theology_summary": string,
  "worship_style": "liturgical" | "traditional-hymns" | "blended" | "contemporary" | "charismatic" | null,
  "worship_style_detail": string,
  "pull_quote": string,
  "statement_of_faith": string[]
}

Field rules:
- denomination: specific affiliation if explicitly stated (e.g., "Southern Baptist", "PCA", "ELCA", "Roman Catholic", "Non-denominational"). Null if not clear from text.
- theological_stance: one of three buckets, inferred only from explicit doctrinal/social-issue language. Null if no signal.
- service_languages: language names used in services (e.g., ["English"], ["English", "Spanish"]). Empty list if unclear.
- programs: 3-8 short noun phrases for active ministries (e.g., "youth group", "food pantry", "small groups"). Empty list if none mentioned.
- vibe_tags: 3-7 short adjectives/tags describing community feel (e.g., "family-friendly", "intergenerational"). Avoid generic words like "Christian" or "welcoming".
- community_summary: ONE or TWO sentences (60-200 chars) describing WHO this congregation is — neighborhood, demographics, atmosphere. No hype, no marketing language. Empty string "" if text gives no signal.
- theology_summary: ONE or TWO sentences (60-200 chars) describing WHAT they teach — doctrinal emphasis, preaching style, distinctive theology. Empty string if no signal.
- worship_style: one bucket if discernible from explicit cues (organ/hymnal -> traditional-hymns; band/contemporary -> contemporary; mass/eucharist/responsive readings -> liturgical; spirit-filled/charismatic-language -> charismatic; mix of hymns + band -> blended). Null if unclear.
- worship_style_detail: ONE short sentence (under 120 chars) describing what a service feels like (instruments, music style, formality, sermon length). Empty string if no signal.
- pull_quote: a verbatim sentence (max 200 chars) from the website that captures the church's self-description in their own voice — pastor's letter, mission statement, welcome note. Must be a real quote from the source text, not generated. Empty string if no good candidate.
- statement_of_faith: 3-8 short bullets (each under 120 chars) listing doctrinal beliefs, ONLY if the site has an explicit statement-of-faith / what-we-believe / doctrine page. Each bullet should be a single belief (e.g., "Scripture is inspired and authoritative", "Salvation by grace through faith"). Empty list if no such page.

If the text appears to be junk, an error page, or unrelated to a church, return all nulls/empty values.
"""


class ExtractionError(Exception):
    pass


def _truncate(text: str, limit: int = MAX_INPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[...truncated]"


def gather_text(con: sqlite3.Connection, church_id: int) -> str:
    rows = con.execute(
        """
        SELECT kind, text FROM website_pages
        WHERE church_id=? AND status_code=200 AND text IS NOT NULL AND text != ''
        ORDER BY CASE kind
            WHEN 'homepage'   THEN 0
            WHEN 'about'      THEN 1
            WHEN 'beliefs'    THEN 2
            WHEN 'ministries' THEN 3
            WHEN 'services'   THEN 4
            ELSE 5 END
        """,
        (church_id,),
    ).fetchall()
    parts = [f"# {kind}\n{text}" for kind, text in rows]
    return _truncate("\n\n".join(parts))


def _parse_json_object(content: str) -> dict[str, Any]:
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1:
        raise ExtractionError(f"no JSON object in model output: {content[:200]}")
    return json.loads(s[start : end + 1])


def call_llm(text: str, *, api_key: str | None = None, client: httpx.Client | None = None) -> dict[str, Any]:
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ExtractionError("OPENROUTER_API_KEY not set")

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Website text follows:\n\n{text}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://churchmap.vercel.app",
        "X-Title": "ChurchMap website extraction",
    }
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=HTTP_TIMEOUT_S)
    try:
        r = client.post(OPENROUTER_URL, json=payload, headers=headers)
        if r.status_code != 200:
            raise ExtractionError(f"OpenRouter HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ExtractionError(f"unexpected response shape: {e}; body={body}")
        return _parse_json_object(content)
    finally:
        if owns_client:
            client.close()


def _normalize(obj: dict[str, Any]) -> dict[str, Any]:
    def s(v): return v.strip() if isinstance(v, str) else None
    def clamp(v, n):
        v = s(v) or ""
        return v[:n].rstrip()
    def lst(v, item_max: int | None = None):
        if not isinstance(v, list):
            return []
        out = []
        for x in v:
            t = (s(x) or "")
            if not t:
                continue
            if item_max:
                t = t[:item_max].rstrip()
            out.append(t)
        return out
    stance = obj.get("theological_stance")
    style = obj.get("worship_style")
    return {
        "denomination":         s(obj.get("denomination")),
        "theological_stance":   stance if stance in {"traditional", "moderate", "progressive"} else None,
        "service_languages":    lst(obj.get("service_languages")),
        "programs":             lst(obj.get("programs")),
        "vibe_tags":            lst(obj.get("vibe_tags")),
        "community_summary":    clamp(obj.get("community_summary") or obj.get("summary"), 240),
        "theology_summary":     clamp(obj.get("theology_summary"), 240),
        "worship_style":        style if style in WORSHIP_STYLES else None,
        "worship_style_detail": clamp(obj.get("worship_style_detail"), 160),
        "pull_quote":           clamp(obj.get("pull_quote"), 240),
        "statement_of_faith":   lst(obj.get("statement_of_faith"), item_max=160)[:8],
    }


def extract_for_church(con: sqlite3.Connection, church_id: int, *, api_key: str | None = None) -> dict[str, Any] | None:
    text = gather_text(con, church_id)
    if not text:
        _mark_status(con, church_id, "no-text")
        return None
    try:
        raw = call_llm(text, api_key=api_key)
    except ExtractionError as e:
        log.warning("church %s extraction failed: %s", church_id, e)
        _mark_status(con, church_id, f"error:{type(e).__name__}")
        return None
    norm = _normalize(raw)
    _persist(con, church_id, norm)
    return norm


def _persist(con: sqlite3.Connection, church_id: int, norm: dict[str, Any]) -> None:
    tags = {
        "theological_stance":   norm["theological_stance"],
        "service_languages":    norm["service_languages"],
        "programs":             norm["programs"],
        "vibe_tags":            norm["vibe_tags"],
        "theology_summary":     norm["theology_summary"] or None,
        "worship_style":        norm["worship_style"],
        "worship_style_detail": norm["worship_style_detail"] or None,
        "pull_quote":           norm["pull_quote"] or None,
        "statement_of_faith":   norm["statement_of_faith"],
    }
    con.execute(
        """
        UPDATE Churches SET
            website_summary          = ?,
            extracted_tags           = ?,
            extracted_at             = ?,
            extracted_prompt_version = ?,
            extracted_status         = 'ok',
            denomination             = COALESCE(?, denomination)
        WHERE church_id = ?
        """,
        (
            norm["community_summary"] or None,
            json.dumps(tags, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
            PROMPT_VERSION,
            norm["denomination"],
            church_id,
        ),
    )
    con.commit()


def _mark_status(con: sqlite3.Connection, church_id: int, status: str) -> None:
    con.execute(
        "UPDATE Churches SET extracted_status=?, extracted_at=? WHERE church_id=?",
        (status, datetime.now(timezone.utc).isoformat(), church_id),
    )
    con.commit()
