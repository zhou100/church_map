"""Website extraction prompt v3 (Phase B).

Ported from backend/scrapers/website_extract.py (v2, frozen) with three
additions: per-field confidence, verbatim source snippets, and stricter
schema validation. Bump PROMPT_VERSION whenever the schema or rules change
so the eval harness can baseline against prior versions.

The prompt is the IP. Don't edit it without bumping the version string and
re-running representative churches through the eval harness.

Revision v3.1 (2026-07-24) — same schema, two rule fixes the eval measured:

- service_languages was scoring 0.588, the worst field. "Empty list if
  unclear" was taken literally, so any page that didn't name a language in
  so many words returned [] — most pages. A congregation publishes in the
  language it worships in, and that inference is what a language filter
  needs to exist at all.
- Values came back in the source page's language: a Korean parish extracted
  denomination "장로교회" and programs ["교사모집", …]. Correct, and useless
  to an English-facing facet or filter. pull_quote is exempt — it is
  validated as a verbatim substring of the source.

Extraction is driven by `extract_status = 'pending'`, not by prompt
version, so this only affects churches extracted from here on. Existing
rows keep their v3 values until something deliberately re-queues them.
"""
from __future__ import annotations

PROMPT_VERSION = "2026-07-24.v3.1"
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

Write every extracted value in English, even when the source page is in another language — this data is read by English-speaking users and filtered on. That covers denomination ("Presbyterian", not "장로교회"), language names ("Haitian Creole", not "Kreyol"), programs, vibe_tags and the summaries. The ONE exception is pull_quote, which must stay exactly as written in the source.

Field rules:
- denomination: specific affiliation if explicitly stated (e.g., "Southern Baptist", "PCA", "ELCA", "Roman Catholic", "Non-denominational"). Give the denomination, not the congregation's own name — a church called "First Church of Christ, Scientist" is denomination "Christian Science". Null if not clear from text.
- theological_stance: one of three buckets, inferred only from explicit doctrinal/social-issue language. Null if no signal.
- service_languages: language names used in services (e.g., ["English"], ["English", "Spanish"]). List every language the text names for a service. If it names none, use the language the page itself is written in — a congregation almost always publishes in the language it worships in. Empty list only when the text is too short or too garbled to tell.
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
