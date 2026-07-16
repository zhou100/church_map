"""LLM judge for the prose fields of a website extraction.

The deterministic scorer in run.py handles the structured fields
(denomination, theological_stance, service_languages, worship_style) by
comparing against reference labels. The prose fields — summaries, tags,
pull quote — don't have a single right answer, so a stronger model judges
them directly against the source text instead: is the value supported by
the text, and does it capture what's clearly there?

Verdicts are cached alongside extraction outputs (see run.py), so CI
re-scores from cache with zero LLM calls. Bump JUDGE_VERSION whenever the
rubric changes so cached verdicts can be invalidated knowingly.

One judge call per example, returning per-field verdicts as strict JSON.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from backend.scrapers_v2.extract import call_llm

JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "google/gemini-2.5-pro")
JUDGE_VERSION = "2026-07-16.j1"

# Fields the judge evaluates. Structured enum-ish fields stay deterministic.
JUDGE_FIELDS = (
    "programs",
    "vibe_tags",
    "community_summary",
    "theology_summary",
    "worship_style_detail",
    "pull_quote",
    "statement_of_faith",
)

JUDGE_SYSTEM_PROMPT = """You are grading a structured extraction made from a Christian church's website text. You will receive the source text and the extraction. Judge ONLY these fields:

programs, vibe_tags, community_summary, theology_summary, worship_style_detail, pull_quote, statement_of_faith

For each field, verdict ok=true requires BOTH:
1. Faithful — everything in the value is supported by the source text. No fabricated programs, no invented claims, no marketing spin added.
2. Complete enough — if the text clearly provides signal for the field, the value must capture it. An empty value is ok ONLY when the text genuinely lacks signal for that field.

Field-specific notes:
- programs: each listed item must correspond to a ministry/activity named in the text.
- vibe_tags: tags must be grounded in the text's actual self-description, not generic filler.
- community_summary: must describe WHO the congregation is, accurately and without hype.
- theology_summary: must describe WHAT they teach, grounded in doctrinal statements in the text.
- worship_style_detail: must reflect explicit worship cues (instruments, liturgy, music style).
- pull_quote: must be a sentence that appears in the text and represents the church's voice.
- statement_of_faith: bullets must come from an explicit what-we-believe section; empty is ok when the text has none.

Return STRICT JSON, no prose, no markdown — one entry per field above:
{
  "programs": {"ok": true, "reason": "<10 words max>"},
  "vibe_tags": {"ok": false, "reason": "<10 words max>"},
  ...
}
"""


def build_judge_input(text: str, fields: dict[str, Any]) -> str:
    """Compose the user-message body: source text, then the extraction.

    call_llm prefixes the user message with "Website text follows:", so the
    source text goes first to keep that framing coherent.
    """
    judged = {k: fields.get(k) for k in JUDGE_FIELDS}
    return (
        f"{text}\n\n"
        "--- EXTRACTION TO EVALUATE (JSON) ---\n"
        f"{json.dumps(judged, ensure_ascii=False, indent=1)}"
    )


async def judge_example(
    text: str,
    fields: dict[str, Any],
    *,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    model: str = JUDGE_MODEL,
) -> dict[str, dict]:
    raw = await call_llm(
        build_judge_input(text, fields),
        api_key=api_key,
        client=client,
        model=model,
        system_prompt=JUDGE_SYSTEM_PROMPT,
    )
    return parse_verdicts(raw)


def parse_verdicts(obj: Any) -> dict[str, dict]:
    """Validate judge output into {field: {"ok": bool, "reason": str}}.

    Malformed or missing fields are dropped — the scorer skips fields with
    no verdict rather than guessing.
    """
    verdicts: dict[str, dict] = {}
    if not isinstance(obj, dict):
        return verdicts
    for field in JUDGE_FIELDS:
        v = obj.get(field)
        if not isinstance(v, dict) or not isinstance(v.get("ok"), bool):
            continue
        reason = v.get("reason")
        verdicts[field] = {
            "ok": v["ok"],
            "reason": reason if isinstance(reason, str) else "",
        }
    return verdicts


_WS = re.compile(r"\s+")


def verbatim_pull_quote_ok(quote: str | None, text: str) -> bool:
    """Whitespace-normalized substring check; empty quotes pass (the judge
    decides whether empty was acceptable)."""
    q = _WS.sub(" ", (quote or "").strip())
    if not q:
        return True
    return q.lower() in _WS.sub(" ", text).lower()
