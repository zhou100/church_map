"""Website extraction prompt v3 (Phase B).

Ported from backend/scrapers/website_extract.py (v2, frozen) with three
additions: per-field confidence, verbatim source snippets, and stricter
schema validation. Bump PROMPT_VERSION whenever the schema or rules change
so the eval harness can baseline against prior versions.

The prompt is the IP. Don't edit it without bumping the version string and
re-running representative churches through the eval harness.
"""
from __future__ import annotations

PROMPT_VERSION = "2026-05-08.v3"
MODEL = "google/gemini-2.5-flash"

WORSHIP_STYLES = {
    "liturgical",
    "traditional-hymns",
    "blended",
    "contemporary",
    "charismatic",
}
THEOLOGICAL_STANCES = {"traditional", "moderate", "progressive"}
EXTRACTABLE_FIELDS = {
    "denomination",
    "theological_stance",
    "service_languages",
    "programs",
    "vibe_tags",
    "community_summary",
    "theology_summary",
    "worship_style",
    "worship_style_detail",
    "pull_quote",
    "statement_of_faith",
}

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
  "statement_of_faith": string[],
  "_confidence": { "<field_name>": number, ... },
  "_source_snippets": { "<field_name>": string, ... }
}

Field rules:
- denomination: specific affiliation if explicitly stated (e.g., "Southern Baptist", "PCA", "ELCA", "Roman Catholic", "Non-denominational"). Null if not clear from text.
- theological_stance: one of three buckets, inferred only from explicit doctrinal/social-issue language. Null if no signal.
- service_languages: language names used in services (e.g., ["English"], ["English", "Spanish"]). Empty list if unclear.
- programs: 3-8 short noun phrases for active ministries (e.g., "youth group", "food pantry", "small groups"). Empty list if none mentioned.
- vibe_tags: 3-7 short adjectives/tags describing community feel (e.g., "family-friendly", "intergenerational"). Avoid generic words like "Christian" or "welcoming".
- community_summary: ONE or TWO sentences (60-200 chars) describing WHO this congregation is. No hype, no marketing language. Empty string "" if text gives no signal.
- theology_summary: ONE or TWO sentences (60-200 chars) describing WHAT they teach. Empty string if no signal.
- worship_style: one bucket if discernible from explicit cues. Null if unclear.
- worship_style_detail: ONE short sentence (under 120 chars) describing what a service feels like. Empty string if no signal.
- pull_quote: a verbatim sentence (max 200 chars) from the website that captures the church's self-description in their own voice. Must be a real quote from the source text. Empty string if no good candidate.
- statement_of_faith: 3-8 short bullets (each under 120 chars), ONLY if the site has an explicit statement-of-faith / what-we-believe page. Empty list otherwise.

Confidence and source snippets:
- _confidence is a map from field name to a number in [0.0, 1.0] expressing your calibrated belief that the field is correct. Use 0.9+ only when the source text is unambiguous. Include only fields where you produced a non-null/non-empty value.
- _source_snippets is a map from field name to a verbatim substring of the input text (max 160 chars) that supports the extracted value. The value MUST appear character-for-character in the input. If no clean substring exists, omit the field rather than fabricating one.

If the text appears to be junk, an error page, or unrelated to a church, return all nulls/empty values and an empty _confidence and _source_snippets.
"""
